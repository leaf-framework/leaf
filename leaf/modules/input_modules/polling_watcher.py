import threading
from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


class PollingWatcher(EventWatcher):
    """
    A base class for watchers that perform periodic polling
    to check for events like start, stop, or measurement.

    It supports callback registration and background polling.
    """

    def __init__(
        self,
        interval: int,
        metadata_manager: MetadataManager,
        callbacks: list[Callable[[str, Any], None]] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the PollingWatcher.

        Args:
            interval (int): Polling interval in seconds.
            metadata_manager (MetadataManager): Equipment metadata manager.
            callbacks (Optional[List[Callable]]): List of event callbacks.
            error_holder (Optional[ErrorHolder]): Central error tracker.
        """
        super().__init__(metadata_manager, callbacks=callbacks, error_holder=error_holder)

        self._interval: int = interval
        self._thread: threading.Thread | None = None
        # Set by stop() so the poll loop wakes at once instead of finishing a full interval.
        self._stop_event: threading.Event = threading.Event()
        self._term_map = {
            self.start_message: metadata_manager.start,
            self.stop_message: metadata_manager.stop,
            self.measurement_message: metadata_manager.measurement,
        }

    def start_message(self, data: Any) -> None:
        """Dispatch start message to callbacks."""
        self._dispatch_callback(self._term_map[self.start_message], data)

    def stop_message(self, data: Any) -> None:
        """Dispatch stop message to callbacks."""
        self._dispatch_callback(self._term_map[self.stop_message], data)

    def measurement_message(self, data: Any) -> None:
        """Dispatch measurement message to callbacks."""
        self._dispatch_callback(self._term_map[self.measurement_message], data)

    @abstractmethod
    def _fetch_data(self) -> dict[str, dict | None]:
        """
        Abstract method that should be overridden to fetch
        polling data for 'start', 'stop', and 'measurement'.

        Returns:
            dict: A dictionary with optional data for each type.
        """
        pass

    def _poll(self) -> None:
        """Background loop for fetching data and dispatching events."""
        while self._running:
            try:
                data = self._fetch_data()

                if data.get("measurement") is not None:
                    self.measurement_message(data["measurement"])

                if data.get("start") is not None:
                    self.start_message(data["start"])

                if data.get("stop") is not None:
                    self.stop_message(data["stop"])
            except Exception as exc:
                logger.error(f"PollingWatcher: error during poll cycle, will retry next interval: {exc}")
                try:
                    self._handle_exception(exc)
                except Exception:
                    # _handle_exception re-raises when no error_holder is
                    # configured (the default -- it's None throughout the
                    # constructor chain unless an adapter explicitly wires
                    # one up). This loop must survive regardless: without
                    # this, a single bad cycle (e.g. a transient hardware
                    # read glitch) silently and permanently kills this
                    # daemon thread -- no crash, no retry, no visible
                    # alert, just an experiment that quietly stops
                    # reporting data.
                    pass

            _ = self._stop_event.wait(self._interval)

    def start(self) -> None:
        """
        Start the watcher and begin polling in a background thread.
        Also triggers the initialization event.
        """
        logger.info("Starting PollingWatcher...")
        if self._running:
            logger.warning("PollingWatcher already running.")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

        super().start()

    def stop(self) -> None:
        """
        Stop the watcher and wait for the background thread to exit.
        """
        logger.info("Stopping PollingWatcher...")
        if not self._running:
            logger.warning("PollingWatcher is not running.")
            return

        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        logger.info("PollingWatcher stopped.")
