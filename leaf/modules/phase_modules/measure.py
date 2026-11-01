import inspect
import threading
import time
from typing import TYPE_CHECKING, Any, cast

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterLogicError, InterpreterError
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

if TYPE_CHECKING:
    from leaf.modules.output_modules.output_module import OutputModule

logger = get_logger(__name__, log_file="measure.log")


class MeasurePhase(PhaseModule):
    """
    Handles the measurement-related actions within a process.
    It transmits measurement data.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager | None = None,
        maximum_message_size: int = 1,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the MeasurePhase with metadata manager and optional maximum_message_size setting.

        Args:
            metadata_manager (Optional[MetadataManager]): Manages metadata associated with the phase.
            maximum_message_size (Optional[int]): The maximum number of measurements in a single message.
            error_holder (Optional[ErrorHolder]): Optional, an error holder to manage phase errors.
        """
        term_builder = (
            metadata_manager.experiment.measurement
            if metadata_manager is not None
            else "metadata_manager.experiment.measurement"
        )

        super().__init__(term_builder, metadata_manager=metadata_manager, error_holder=error_holder)
        self._maximum_message_size: int = maximum_message_size
        self._tag_mismatches: set[tuple[str, str]] = set()
        # Guards against a second measurement running concurrently with one still
        # draining (e.g. a generator-based interpreter that streams for a long time,
        # or forever). Without this, an overlapping event (e.g. FileWatcher's
        # trailing-modification timer firing on its own thread) could invoke the
        # interpreter a second time while the first call is still in flight.
        self._measurement_lock = threading.Lock()
        # stream() is keyed per-filename rather than sharing _measurement_lock:
        # StreamingAdapter may run several filenames concurrently (e.g. multiple
        # files matching a watch pattern), each on its own thread, and those
        # shouldn't block each other - only two calls for the *same* filename
        # should be mutually exclusive.
        self._stream_locks: dict[Any, threading.Lock] = {}
        self._stream_locks_guard = threading.Lock()

    def update(self, data: Any | None = None, **kwargs: Any) -> list[tuple[str, Any]] | None:
        """
        Called to process new measurements and transmit the data.

        Args:
            data (Optional[Any]): Data to be transmitted.
            **kwargs (Any): Additional arguments used to build the action term.

        Returns:
            Optional[list]: A list of messages or None if an error occurs.
        """
        if data is None:
            excp = AdapterLogicError("Measurement system activated without any data")
            self._handle_exception(excp)
            return None

        if self._interpreter is not None:
            if getattr(self._interpreter, "id", None) is None:
                logger.warning("Interpreter has no experiment id set.")
                self._interpreter.id = "invalid_id"
            exp_id = self._interpreter.id
            if exp_id is None:
                excp = AdapterLogicError("Trying to transmit measurements outside of experiment (No experiment id)")
                self._handle_exception(excp)

            if not self._measurement_lock.acquire(blocking=False):
                logger.warning("Interpreter is still processing a previous measurement; dropping this event.")
                return None
            try:
                try:
                    result = self._interpreter.measurement(data)
                except Exception as ex:
                    leaf_exp = InterpreterError(ex)
                    self._handle_exception(leaf_exp)
                    return None

                if result is False:
                    # Case when the interpreter
                    # doesnt want to send a message.
                    return None

                if result is None:
                    excp = AdapterLogicError(
                        "Interpreter couldn't parse measurement, likely metadata has been provided as measurement data."
                    )
                    self._handle_exception(excp)
                    return None
                if isinstance(result, (set, list, tuple)):
                    result = list(result)
                    chunks = [
                        result[i : i + self._maximum_message_size]
                        for i in range(0, len(result), self._maximum_message_size)
                    ]
                    messages = []
                    for index, chunk in enumerate(chunks):
                        if index % 10 == 0:
                            logger.debug(f"Sending chunk {index + 1} of {len(chunks)} with {len(chunk)} measurements.")
                        messages.extend(self._form_message(exp_id, chunk))
                        time.sleep(0.1)
                    return messages
                elif inspect.isgenerator(result):
                    # The interpreter streams measurements lazily instead of building
                    # the full result up front - useful when a source produces data
                    # too fast/large to buffer in one go, or runs indefinitely.
                    messages = []
                    chunk: list[Any] = []
                    chunk_index = 0
                    try:
                        for item in result:
                            chunk.append(item)
                            if len(chunk) >= self._maximum_message_size:
                                if chunk_index % 10 == 0:
                                    logger.debug(f"Sending chunk {chunk_index + 1} with {len(chunk)} measurements.")
                                messages.extend(self._form_message(exp_id, chunk))
                                time.sleep(0.1)
                                chunk = []
                                chunk_index += 1
                    except Exception as ex:
                        leaf_exp = InterpreterError(ex)
                        self._handle_exception(leaf_exp)
                        return messages or None
                    if chunk:
                        messages.extend(self._form_message(exp_id, chunk))
                    return messages
                else:
                    return self._form_message(exp_id, result)
            finally:
                self._measurement_lock.release()
        else:
            experiment_id = kwargs.get("experiment_id", "unknown")
            measurement = kwargs.get("measurement", "unknown")

            action = self._term_builder(experiment_id=experiment_id, measurement=measurement)
            return [(action, data)]

    def stream(self, output: "OutputModule", filename: Any) -> None:
        """
        Drain the interpreter's `stream(filename)` generator, started once
        for the given filename, and transmit each measurement as soon as
        it is produced.

        Unlike update(), this is not triggered per watcher event: the
        calling thread stays inside this call for as long as the
        interpreter's generator keeps yielding - potentially forever - so
        it must be run on its own dedicated thread (see StreamingAdapter).
        Locking is per-filename, so multiple filenames can stream
        concurrently on separate threads; only two calls for the *same*
        filename are mutually exclusive.

        Args:
            output (OutputModule): Output module to transmit each chunk to
                directly, since the calling thread never returns control
                to ProcessModule.process_input for the duration of the stream.
            filename (Any): Passed straight through to interpreter.stream(),
                identifying what the interpreter should read/tail. Typically
                discovered from a watcher's start event rather than fixed
                up front (see StreamingAdapter).
        """
        if self._interpreter is None or not hasattr(self._interpreter, "stream"):
            excp = AdapterLogicError("Interpreter does not implement stream()")
            self._handle_exception(excp)
            return

        lock = self._get_stream_lock(filename)
        if not lock.acquire(blocking=False):
            logger.warning(f"Interpreter is already streaming {filename!r}; ignoring duplicate stream start.")
            return

        if getattr(self._interpreter, "id", None) is None:
            logger.warning("Interpreter has no experiment id set.")
            self._interpreter.id = "invalid_id"
        exp_id = self._interpreter.id

        chunk: list[Any] = []
        try:
            for item in self._interpreter.stream(filename):
                chunk.append(item)
                if len(chunk) >= self._maximum_message_size:
                    for action, result in self._form_message(exp_id, chunk):
                        output.transmit(action, result)
                    chunk = []
            if chunk:
                for action, result in self._form_message(exp_id, chunk):
                    output.transmit(action, result)
        except Exception as ex:
            leaf_exp = InterpreterError(ex)
            self._handle_exception(leaf_exp)
        finally:
            lock.release()

    def _get_stream_lock(self, filename: Any) -> threading.Lock:
        with self._stream_locks_guard:
            if filename not in self._stream_locks:
                self._stream_locks[filename] = threading.Lock()
            return self._stream_locks[filename]

    def _form_message(self, experiment_id: str, result: Any) -> list[tuple]:
        """
        Formulate one or more (topic, data) messages for a measurement result.

        A list/set of points can mix several distinct measurement types
        (e.g. pH, temperature, oxygen) in the same batch. Since the topic
        encodes a single measurement type, each distinct type present in
        the batch is split out into its own message rather than all being
        published under whichever type happened to come first.

        Args:
            experiment_id (str): The ID of the experiment.
            result (Any): The measurement result data.

        Returns:
            list[tuple]: A list of (action, result) tuples.
        """
        if isinstance(result, dict):
            self._add_instance_tags(cast(object, result))
            measurement = self._resolve_measurement(result)
            action = self._term_builder(experiment_id=experiment_id, measurement=measurement)
            return [(action, result)]

        payload = cast(object, result)
        point_json = point_json_of(payload)
        if point_json is not None:
            result = point_json
            self._add_instance_tags(cast(object, result))
            measurement = self._resolve_measurement(result)
            action = self._term_builder(experiment_id=experiment_id, measurement=measurement)
            return [(action, result)]

        if isinstance(result, list):
            converted = []
            for item in cast(list[object], result):
                point_json = point_json_of(item)
                if point_json is not None:
                    converted.append(point_json)
                else:
                    converted.append(item)

            groups: dict[str, list] = {}
            for item in converted:
                self._add_instance_tags(cast(object, item))
                if isinstance(item, dict):
                    key = self._resolve_measurement(item)
                else:
                    key = "unknown"
                groups.setdefault(key, []).append(item)

            messages = []
            for key, group in groups.items():
                action = self._term_builder(experiment_id=experiment_id, measurement=key)
                messages.append((action, group))
            return messages

        excp = AdapterLogicError(f"Unknown measurement data type: {type(result)}")
        self._handle_exception(excp)
        return []

    def _add_instance_tags(self, item: object) -> None:
        """Tag a point with its instance's organisation and department, unless the adapter already did."""
        if self._metadata_manager is None or not isinstance(item, dict) or "fields" not in item:
            return
        tags = cast(dict[str, object], item).setdefault("tags", {})
        if not isinstance(tags, dict):
            return
        for key, value in self._metadata_manager.instance_tags().items():
            current = cast(dict[str, object], tags).get(key)
            if current is None:
                tags[key] = value
            elif str(current) != value and (key, str(current)) not in self._tag_mismatches:
                # Kept as the adapter set it; warned once so every measurement doesn't repeat it
                self._tag_mismatches.add((key, str(current)))
                logger.warning(
                    f"Tag {key}={current!r} differs from the configured {key} {value!r}; keeping {current!r}"
                )

    def _resolve_measurement(self, item: dict) -> str:
        """
        Resolve the measurement label used for the topic's last segment.

        Prefers the "metric" tag (e.g. "temperature", "ph") over the
        top-level "measurement" field, since adapters commonly set
        "measurement" to a constant device/point type shared by every
        point (e.g. all Pioreactor points use "pioreactor"), while the
        "metric" tag is what actually distinguishes one point from another.
        """
        tags = item.get("tags")
        if isinstance(tags, dict) and tags.get("metric"):
            return tags["metric"]

        if item.get("measurement"):
            return item["measurement"]

        return "unknown"


def point_json_of(item: object) -> dict[str, object] | None:
    """JSON of a leafobject LeafPoint (or anything else with to_json()), else None."""
    if isinstance(item, dict):
        return None
    to_json: object = getattr(item, "to_json", None)
    if not callable(to_json):
        return None
    return cast(dict[str, object], to_json())
