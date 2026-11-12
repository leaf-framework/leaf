from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="event_watcher.log")


class EventWatcher(ABC):
    """
    Abstract base class for monitoring and
    extracting specific information from equipment.
    Designed to detect and handle observable events
    (e.g., file creation, sensor readouts).
    """

    def __init__(
        self,
        metadata_manager: MetadataManager | None = None,
        callbacks: list[Callable[[str, Any], None]] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the EventWatcher.

        Args:
            metadata_manager: Used for adapter and experiment metadata.
            callbacks: Callback functions to invoke when an event is triggered.
            error_holder: Optional error tracker for collecting exceptions.
        """
        self._metadata_manager: MetadataManager | None = metadata_manager
        self._error_holder: ErrorHolder | None = error_holder
        self._callbacks: list[Callable[[str, Any], None]] = callbacks or []
        self._running: bool = False

    @abstractmethod
    def start(self) -> None:
        """
        Start the EventWatcher. Must be implemented by subclasses.

        This should begin the watching process and dispatch the initial metadata event.
        """
        self._running = True

    def stop(self) -> None:
        """
        Stop the EventWatcher, halting further event detection.
        """
        self._running = False

    def is_running(self) -> bool:
        """
        Check whether the EventWatcher is actively monitoring.

        Returns:
            True if watching is active; False otherwise.
        """
        return self._running

    def is_connected(self) -> bool:
        """True while the input can deliver data; inputs with a remote connection override this."""
        return self.is_running()

    def security_warnings(self) -> list[str]:
        """Issues of a connection made without credentials or encryption; none for local inputs."""
        return []

    def add_callback(self, callback: Callable[[str, Any], None]) -> None:
        """
        Register a new callback.

        Args:
            callback: A function accepting a (term, data) pair.
        """
        self._callbacks.append(callback)

    def set_error_holder(self, error_holder: ErrorHolder) -> None:
        """
        Assign an ErrorHolder for centralized error tracking.

        Args:
            error_holder: The error holder instance.
        """
        self._error_holder = error_holder

    def set_metadata_manager(self, metadata_manager: MetadataManager) -> None:
        """
        Assign or replace the metadata manager.

        Args:
            metadata_manager: MetadataManager instance to use.
        """
        self._metadata_manager = metadata_manager

    def _dispatch_callback(self, topic: str, data: Any) -> None:
        """
        Dispatch a term and data payload to all registered callbacks.

        Args:
            function: The function that triggered the callback (used to find the term).
            data: Payload data to send to callbacks.
        """
        logger.debug(f"Dispatching callback for topic '{topic}' with data: {data} to {self._callbacks}")
        for callback in self._callbacks:
            callback(topic, data)

    def _handle_exception(self, exception: Exception) -> None:
        """
        Handle an exception by logging it to the error holder (if present).

        Args:
            exception: The exception to handle.
        """
        if self._error_holder:
            self._error_holder.add_error(exception)
        else:
            raise exception
