import threading
import time
from typing import Any, NamedTuple

from leaf.adapters.equipment_adapter import AbstractInterpreter, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.error import ErrorPhase
from leaf.modules.phase_modules.initialisation import InitialisationPhase
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.phase_modules.start import StartPhase
from leaf.modules.phase_modules.stop import StopPhase
from leaf.modules.process_modules.process_module import ProcessModule
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="streaming_adapter.log")

# Mirrors the reconnect backoff used by OPCWatcher (opc_watcher.py) for consistency.
FIRST_RESTART_DELAY = 1
RESTART_RATE = 2
MAX_RESTART_DELAY = 60
# If the previous run stayed up at least this long, treat the next failure
# as a fresh incident rather than continuing to escalate the backoff.
STABLE_RUN_THRESHOLD = 60


class _Stream(NamedTuple):
    thread: threading.Thread
    stop_event: threading.Event


class StreamingAdapter(EquipmentAdapter):
    """
    Adapter for equipment whose interpreter produces measurements
    continuously via its own `stream(filename)` generator, started once per
    detected run, rather than being invoked per discrete measurement event.

    The interpreter must implement `stream(self, filename) -> Iterator[Any]`,
    yielding parsed measurements at its own pace (e.g. tailing a growing
    file). Use this instead of ContinuousExperimentAdapter when the input
    source changes too fast, or too continuously, for a per-event watcher
    callback to keep up.

    Unlike measurement(), stream() is not given data on every call - it has
    no per-event trigger. Instead, what to stream is discovered from the
    watcher's start event (e.g. FileWatcher.on_created configured with
    return_data=False, so it carries the created filepath rather than file
    content) and handed to stream() once, when that run begins. A matching
    stop event (e.g. on_deleted) halts it.

    Multiple filenames can stream concurrently, each on its own thread and
    with independent restart/backoff state: a start event for a filename
    that isn't already active launches a new stream alongside any others; a
    start event for a filename that IS already active restarts just that one.
    """

    def __init__(
        self,
        instance_data: dict[str, Any],
        watcher: EventWatcher,
        output: OutputModule,
        interpreter: AbstractInterpreter,
        maximum_message_size: int | None = 1,
        error_holder: ErrorHolder | None = None,
        metadata_manager: MetadataManager | None = None,
        experiment_timeout: int | None = None,
        external_watcher: ExternalEventWatcher | None = None,
    ):
        """
        Initialise the StreamingAdapter.

        Args:
            instance_data (dict): Instance-level configuration and metadata.
            watcher (EventWatcher): Input module used for start/stop/details
                events. Its start event's data is passed straight through to
                interpreter.stream(filename) - see class docstring.
            output (OutputModule): The output module used to transmit parsed data.
            interpreter (AbstractInterpreter): Must implement stream(filename).
            maximum_message_size (Optional[int]): Max number of measurements per transmission.
            error_holder (Optional[ErrorHolder]): Error tracking object.
            metadata_manager (Optional[MetadataManager]): Optional metadata manager.
            experiment_timeout (Optional[int]): Optional timeout between measurements.
            external_watcher (Optional[ExternalEventWatcher]): Optional listener for external inputs.

        Raises:
            AdapterBuildError: If the interpreter does not implement stream().
        """
        if not hasattr(interpreter, "stream"):
            raise AdapterBuildError("StreamingAdapter requires an interpreter that implements stream(filename)")

        start_p = StartPhase(metadata_manager)
        stop_p = StopPhase(metadata_manager)
        details_p = InitialisationPhase(metadata_manager)
        error_p = ErrorPhase(metadata_manager)
        # Not included in _control_process's phases: measurements are driven
        # entirely by stream(), never by the watcher's measurement-topic
        # dispatch, so this is only ever touched directly by _run_stream_loop.
        self._measure_p = MeasurePhase(metadata_manager, maximum_message_size=maximum_message_size)

        self._control_process = ProcessModule(
            output,
            [start_p, stop_p, details_p, error_p],
            metadata_manager=metadata_manager,
            error_holder=error_holder,
        )

        self._streams: dict[Any, _Stream] = {}
        self._streams_guard = threading.Lock()

        super().__init__(
            instance_data,
            watcher,
            output,
            [self._control_process],
            interpreter,
            metadata_manager=metadata_manager,
            error_holder=error_holder,
            experiment_timeout=experiment_timeout,
            external_watcher=external_watcher,
        )
        # EquipmentAdapter.__init__ calls p.set_interpreter/set_metadata_manager
        # for each phase in _control_process, which no longer includes
        # _measure_p (see above) - wire it up here instead.
        self._measure_p.set_interpreter(interpreter)
        self._measure_p.set_metadata_manager(self._metadata_manager)
        self._measure_p.set_error_holder(error_holder)

        # Separate from the standard process_input wiring: this callback
        # exists purely to learn the filename to stream from a real start
        # event, and to halt the stream on a real stop event.
        self._watcher.add_callback(self._handle_watcher_event)

    def stop(self) -> None:
        """
        Stop the adapter, halting all active streams first.
        """
        with self._streams_guard:
            filenames = list(self._streams.keys())
        for filename in filenames:
            self._stop_stream(filename)
        super().stop()

    def _handle_watcher_event(self, topic, data: Any) -> None:
        """
        Watches for the real start/stop topics dispatched by the watcher
        (as opposed to the process_input wiring used for messaging) purely
        to drive each filename's stream lifecycle.

        Any other event (e.g. the "measurement" topic FileWatcher uses for
        files that already existed when it started watching, via
        _process_existing_files) is treated as an implicit start too, as
        long as we're not already streaming that filename - otherwise a
        file present before the watcher starts would never get streamed at
        all, since it never produces a real "created" event. Once a stream
        is active for a filename, further non-start/stop events for it are
        no-ops; the running stream() call handles tailing on its own.
        """
        if topic() == self._metadata_manager.experiment.start():
            self._launch_stream(data)
        elif topic() == self._metadata_manager.experiment.stop():
            self._stop_stream(data)
        else:
            with self._streams_guard:
                already_streaming = data in self._streams
            if not already_streaming:
                self._launch_stream(data)

    def _launch_stream(self, filename: Any) -> None:
        """
        (Re)launch the background stream thread for the given filename. Any
        existing stream for this SAME filename is halted first; streams for
        other filenames are left untouched and keep running independently.
        """
        self._stop_stream(filename)

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_stream_loop,
            args=(filename, stop_event),
            daemon=True,
            name=f"leaf-stream-{self._metadata_manager.get_instance_id()}-{filename}",
        )
        with self._streams_guard:
            self._streams[filename] = _Stream(thread, stop_event)
        thread.start()

    def _stop_stream(self, filename: Any) -> None:
        """
        Signal the given filename's stream generation to stop and wait
        briefly for it to exit. If interpreter.stream() is blocked
        mid-iteration (not suspended at a yield), it cannot be forced to
        stop; the join is best-effort and the thread is a daemon so it
        won't block process shutdown, but it may keep running until that
        blocking call returns.
        """
        with self._streams_guard:
            stream = self._streams.pop(filename, None)
        if stream is None:
            return
        stream.stop_event.set()
        stream.thread.join(timeout=5)

    def _run_stream_loop(self, filename: Any, stop_event: threading.Event) -> None:
        """
        Run interpreter.stream(filename) via MeasurePhase.stream(), restarting
        it with exponential backoff whenever it ends - whether by returning
        normally or by raising - since neither is expected while this run is
        meant to be active. Stops restarting once stop_event is set (either
        by a real stop event for this filename, or by a newer start event
        superseding it).

        Note: if the interpreter doesn't keep track of its own resume point
        (e.g. a file offset held on the interpreter instance), a restart
        will call stream(filename) fresh and may re-emit data from the beginning.
        """
        restart_delay = FIRST_RESTART_DELAY
        while not stop_event.is_set():
            started_at = time.monotonic()
            self._measure_p.stream(self._output, filename)
            ran_for = time.monotonic() - started_at

            if stop_event.is_set():
                break

            if ran_for >= STABLE_RUN_THRESHOLD:
                restart_delay = FIRST_RESTART_DELAY

            logger.warning(
                f"Interpreter stream({filename!r}) for {self._metadata_manager.get_instance_id()} ended "
                f"after {ran_for:.1f}s; restarting in {restart_delay}s."
            )
            if stop_event.wait(timeout=restart_delay):
                break
            restart_delay = min(restart_delay * RESTART_RATE, MAX_RESTART_DELAY)

        logger.info(f"Streaming thread for {self._metadata_manager.get_instance_id()} ({filename!r}) exiting.")
