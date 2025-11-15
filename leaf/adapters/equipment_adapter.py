import logging
import time
from abc import ABC, abstractmethod
from threading import Event
from typing import Any, Optional

from leaf_register.metadata import MetadataManager

from leaf.error_handler import exceptions
from leaf.error_handler.exceptions import LEAFError
from leaf.error_handler.error_holder import ErrorHolder

from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.modules.output_modules.output_module import OutputModule
from leaf.utility.logger.logger_utils import get_logger
from leaf.modules.process_modules.process_module import ProcessModule
from leaf.modules.process_modules.external_event_process import ExternalEventProcess

class AbstractInterpreter(ABC):
    """
    Abstract base class for interpreters.

    Interpreters are responsible for transforming raw input data into a
    structured format suitable for processing and output. Each adapter
    uses one interpreter instance to convert metadata and measurement
    input into a standardised structure.
    """

    def __init__(self, error_holder: Optional[ErrorHolder] = None):
        """
        Initialise the interpreter.

        Args:
            error_holder (Optional[ErrorHolder]): Optional holder for logging
                                                  or deferring error handling.
        """
        self.id: str = "undefined"
        self.TIMESTAMP_KEY: str = "timestamp"
        self.EXPERIMENT_ID_KEY: str = "experiment_id"
        self.MEASUREMENT_HEADING_KEY: str = "measurement_types"
        self.RUNTIME_KEY = "run_time"
        self._error_holder = error_holder
        self._start_time = None
        self._last_measurement = None
        self._is_running = False

    def set_error_holder(self, error_holder: Optional[ErrorHolder]) -> None:
        """Assign an ErrorHolder instance to the interpreter."""
        self._error_holder = error_holder

    def metadata(self, data: Any) -> dict[str, Any]:
        """
        Parse metadata input and return it in structured form.

        Default implementation records the experiment start timestamp.
        Override this method in your interpreter if you need custom metadata processing.

        Args:
            data (Any): Raw metadata from input module.

        Returns:
            dict[str, Any]: Parsed metadata dictionary with timestamp.
        """
        self._start_time = time.time()
        return {self.TIMESTAMP_KEY: self._start_time}

    @abstractmethod
    def measurement(self, data: Any) -> Any:
        """
        Parse a measurement payload.

        Args:
            data (Any): Raw measurement data.

        Returns:
            Any: Parsed or transformed measurement data.
        """
        self._last_measurement = time.time()
        return data

    def get_last_measurement_time(self) -> Optional[float]:
        """Return the timestamp of the last successful measurement."""
        return self._last_measurement

    def experiment_stop(self, data: Any = None) -> Any:
        """
        Clear internal state for stopping experiment tracking.

        Args:
            data (Any): Optional additional data for stop logic.

        Returns:
            Any: Forwarded or cleaned-up stop payload.
        """
        if isinstance(data,dict):
            if self.TIMESTAMP_KEY not in data:
                data[self.TIMESTAMP_KEY] = time.time()
            if self.EXPERIMENT_ID_KEY not in data:
                data[self.EXPERIMENT_ID_KEY] = self.id
            if self._start_time is not None:
                data[self.RUNTIME_KEY] = time.time() - self._start_time
        self._last_measurement = None
        self._start_time = None
        return data

    def _handle_exception(self, exception: LEAFError) -> None:
        """
        Route exceptions to the error handler or raise directly.

        Args:
            exception (LEAFError): Exception to handle or raise.
        """
        if self._error_holder is not None:
            self._error_holder.add_error(exception)
        else:
            raise exception


class EquipmentAdapter(ABC):
    """
    Base class for all equipment adapters.

    Handles coordination of:
      - data input (via watchers),
      - processing (via processes),
      - output (via output modules),
      - and error handling.

    Subclasses implement concrete workflows (e.g., continuous, discrete).
    """

    def __init__(
        self,
        instance_data: dict[str, Any],
        watcher: EventWatcher,
        output: OutputModule,
        process_adapters: ProcessModule | list[ProcessModule],
        interpreter: AbstractInterpreter,
        metadata_manager: Optional[MetadataManager] = None,
        error_holder: Optional[ErrorHolder] = None,
        experiment_timeout: Optional[int] = None,
        external_watcher: Optional[ExternalEventWatcher] = None
    ):
        """
        Initialise the equipment adapter.

        Args:
            instance_data (dict): Configuration and metadata for the adapter instance.
            watcher (EventWatcher): Input module responsible for receiving input events.
            output (OutputModule): Output module to send processed data.
            process_adapters (ProcessModule | list): Phase processors to handle logic.
            interpreter (AbstractInterpreter): Logic for transforming raw input to usable data.
            metadata_manager (Optional[MetadataManager]): Metadata coordinator.
            error_holder (Optional[ErrorHolder]): Centralised error recording and dispatch.
            experiment_timeout (Optional[int]): Optional timeout in seconds for experiment stall detection.
            external_watcher (Optional[ExternalEventWatcher]): Optional secondary input for external events.
        """
        self._output = output
        self._error_holder = error_holder

        if not isinstance(process_adapters, (list, tuple, set)):
            process_adapters = [process_adapters]
        self._processes: list[ProcessModule] = list(process_adapters)
        for p in self._processes:
            p.set_error_holder(error_holder)

        self._interpreter = interpreter
        for p in self._processes:
            p.set_interpreter(interpreter)
        interpreter.set_error_holder(error_holder)

        self._metadata_manager = metadata_manager or MetadataManager()
        self._metadata_manager.add_instance_data(instance_data)

        self._watcher = watcher
        for p in self._processes:
            self._watcher.add_callback(p.process_input)
            p.set_metadata_manager(self._metadata_manager)
        self._watcher.set_error_holder(error_holder)

        ins_id = self._metadata_manager.get_instance_id()
        self._logger = get_logger(
            name=f"{__name__}.{ins_id}",
            log_file=f"{ins_id}.log",
            error_log_file=f"{ins_id}_error.log",
            log_level=logging.INFO,
        )

        self._stop_event = Event()
        self._stop_event.set()
        self._experiment_timeout = experiment_timeout

        self._external_watcher = external_watcher
        if self._external_watcher is not None:
            self._external_watcher.set_metadata_manager(self._metadata_manager)
            self._external_process = ExternalEventProcess(
                output, self._metadata_manager, self._error_holder
            )
            self._external_process.set_error_holder(self._error_holder)
            self._external_process.set_interpreter(interpreter)
            self._external_watcher.add_callback(self._external_process.process_input)

    def is_running(self) -> bool:
        """
        Check if the adapter is actively running.

        Returns:
            bool: True if input/output are active and adapter is not stopped.
        """
        return (self._watcher.is_running() and 
                self._output.is_connected() and 
                not self._stop_event.is_set())

    def start(self) -> None:
        """
        Begin running the adapter.

        Starts input watchers, begins monitoring for errors,
        and invokes appropriate error-driven control logic.
        """
        if not self._metadata_manager.is_valid():
            ins_id = self._metadata_manager.get_instance_id()
            missing_data = self._metadata_manager.get_missing_metadata()
            excp = exceptions.AdapterLogicError(
                f"{ins_id} is missing data: {missing_data}",
                severity=exceptions.SeverityLevel.CRITICAL,
            )
            self._logger.error("Critical error, shutting down adapter", exc_info=excp)
            self._handle_exception(excp)
            return self.stop()

        try:
            self._watcher.start()
            if self._external_watcher:
                self._external_watcher.start()

            self._stop_event.clear()
            # Expose adapter on all channels.
            for process in self._processes:
                process.process_input(self._metadata_manager.details,
                                      self._metadata_manager.get_data())
            while not self._stop_event.is_set():
                time.sleep(1)
                if not self._error_holder:
                    continue

                cur_errors = self._error_holder.get_unseen_errors()
                self.transmit_errors(cur_errors)

                for error, _ in cur_errors:
                    if error.severity == exceptions.SeverityLevel.CRITICAL:
                        self._logger.error("Critical error, stopping adapter", exc_info=error)
                        self._stop_event.set()
                        self.stop()

                    elif error.severity == exceptions.SeverityLevel.ERROR:
                        self._logger.error("Error, restarting adapter", exc_info=error)
                        self.stop()
                        return self.start()

                    elif error.severity == exceptions.SeverityLevel.WARNING:
                        self._handle_warning(error)

                    elif error.severity == exceptions.SeverityLevel.INFO:
                        self._logger.info("Info: %s", error, exc_info=error)

                if self._experiment_timeout:
                    lmt = self._interpreter.get_last_measurement_time()
                    if lmt and (time.time() - lmt > self._experiment_timeout):
                        self._handle_exception(exceptions.HardwareStalledError("Experiment timeout"))

        except KeyboardInterrupt:
            self._logger.info("Keyboard interrupt received.")
            self._stop_event.set()

        except Exception as e:
            self._logger.error(f"Unexpected error: {e}", exc_info=True)
            self._stop_event.set()

        finally:
            self._logger.info("Stopping adapter.")
            self._watcher.stop()
            self.stop()

    def _handle_warning(self, error: LEAFError) -> None:
        """
        Handle warnings by attempting recovery actions (restart input, etc).

        Args:
            error (LEAFError): The warning-level exception to evaluate.
        """
        if isinstance(error, exceptions.InputError):
            self._logger.warning("Input error, restarting watcher", exc_info=error)
            if self._watcher.is_running():
                self._watcher.stop()
            self._watcher.start()

        elif isinstance(error, exceptions.HardwareStalledError):
            self._logger.warning("Hardware stalled, stopping processes", exc_info=error)
            for p in self._processes:
                p.stop()
            self._interpreter.experiment_stop()
            if self._watcher.is_running():
                self._watcher.stop()
            self._watcher.start()

        elif isinstance(error, exceptions.ClientUnreachableError):
            self._logger.warning("Client unreachable", exc_info=error)
            if error.client:
                error.client.disconnect()
                time.sleep(1)
                error.client.connect()

    def stop(self) -> None:
        """
        Stop the adapter and all associated processes and watchers.
        """
        self._stop_event.set()
        if self._watcher.is_running():
            self._watcher.stop()

        for p in self._processes:
            p.stop()

        if self._external_watcher:
            self._external_watcher.stop()

    def withdraw(self) -> None:
        """
        Withdraw the adapter from being visible, but leave it running.

        Calls withdraw on each active process.
        """
        for process in self._processes:
            process.withdraw()

    def transmit_errors(self, errors: list[tuple[LEAFError, str]] = None) -> None:
        """
        Push errors to the output module(s) via each process.

        Args:
            errors (list[LEAFError], optional): A list of errors to transmit.
        """
        errors = errors or self._error_holder.get_unseen_errors()
        for error, _ in errors:
            if not isinstance(error, LEAFError):
                self._logger.error("Non-LEAF error added to error holder", 
                                   exc_info=error)
                return self.stop()

            error_json = error.to_json()
            for process in self._processes:
                process.transmit_error(error_json)
                time.sleep(0.1)

    def _handle_exception(self, exception: Exception) -> None:
        """
        Record or raise an exception.

        Args:
            exception (Exception): Exception to handle.
        """
        if self._error_holder:
            self._error_holder.add_error(exception)
        else:
            raise exception