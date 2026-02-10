import os
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterLogicError, ClientUnreachableError, LEAFError
from leaf.modules.output_modules.topic_store import TopicStore


class OutputModule(ABC):
    """
    Abstract base class for output modules responsible for transmitting
    data to external systems such as databases or network services.
    Supports fallback behavior and connection management.
    """

    # Class-level failure tracking across all output modules
    _global_failure_count = 0
    _max_failures_before_reboot = int(os.getenv("LEAF_MAX_FAILURES_BEFORE_REBOOT", "5"))
    _gui_mode = False
    _global_topic_store: TopicStore = TopicStore()

    def __init__(
        self,
        fallback: Optional["OutputModule"] = None,
        error_holder: ErrorHolder | None = None,
        name: str | None = None,
    ) -> None:
        """
        Initialize the OutputModule.

        Args:
            fallback (Optional[OutputModule]): Optional fallback output module.
            error_holder (Optional[ErrorHolder]): Error tracking mechanism.
            name (Optional[str]): Human-readable name for this module instance.
                If not provided, a default is derived from the class name.

        Raises:
            AdapterLogicError: If fallback is not a valid OutputModule.
        """
        if fallback is not None and not isinstance(fallback, OutputModule):
            raise AdapterLogicError("Output fallback must be an OutputModule.")

        self._fallback: OutputModule | None = fallback
        self._parallels: list[OutputModule] = []
        self._error_holder: ErrorHolder | None = error_holder
        self._enabled: float | None = None
        self._name: str | None = name
        self._topic_store: TopicStore = TopicStore()

    @abstractmethod
    def transmit(self, topic: str, data: str) -> None:
        """
        Transmit data to the output system.

        Args:
            topic (str): The topic or destination identifier.
            data (str): Serialized data to be transmitted.
        """
        pass

    @abstractmethod
    def pop(self, key: str | None = None) -> Any:
        """
        Retrieve and remove a stored message.

        This removes the message from storage upon successful retrieval,
        ensuring messages are sent only once.

        Args:
            key (Optional[str]): Specific key/topic to pop from buffer.
                                If None, implementation may pop from any available key.

        Returns:
            Any: Retrieved message tuple (topic, data) or None if no messages.
        """
        pass

    @abstractmethod
    def connect(self) -> None:
        """
        Establish a connection to the output system.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Close the connection to the output system.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check the output system connection status.

        Returns:
            bool: True if connected, False otherwise.
        """
        pass

    def flush(self, topic: str) -> None:
        """
        Flush any held data from the system, if implemented.

        Args:
            topic (str): Topic to flush.
        """
        if self._fallback is not None:
            self._fallback.flush(topic)

    def subscribe(self, topic: str) -> None:
        """
        Listen on the specified topic if supported by the module.

        Args:
            topic (str): Topic to subscribe to.
        """
        if self._fallback is not None:
            self._fallback.subscribe(topic)

    def fallback(self, topic: str, data: str) -> bool:
        """
        Attempt to transmit data using the fallback module.

        Args:
            topic (str): Topic for the message.
            data (str): Data to transmit.

        Returns:
            bool: True if fallback succeeded, False otherwise.
        """
        if self._fallback is not None:
            return self._fallback.transmit(topic, data)
        else:
            self._handle_no_fallback_available()
            return False

    def _handle_no_fallback_available(self) -> None:
        """
        Handle the case when no fallback output mechanisms are available.
        Increments failure counter and triggers app reboot if threshold is exceeded.
        """
        OutputModule._global_failure_count += 1

        error_msg = (
            f"Cannot store data, no output mechanisms available. "
            f"Failure count: {OutputModule._global_failure_count}/"
            f"{OutputModule._max_failures_before_reboot}"
        )

        self._handle_exception(ClientUnreachableError(error_msg))

        if OutputModule._global_failure_count >= OutputModule._max_failures_before_reboot:
            from leaf.utility.logger.logger_utils import get_logger

            logger = get_logger(__name__)
            logger.critical(
                f"Maximum failures ({OutputModule._max_failures_before_reboot}) reached. "
                "All output mechanisms have failed. Triggering application exit."
            )
            self._trigger_exit()

    def _trigger_exit(self) -> None:
        """
        Trigger application exit by exiting the process.
        The application should be managed by a process supervisor that will restart it.
        In GUI mode, the exit is skipped to allow the user to see the error and fix the config.
        """
        from leaf.utility.logger.logger_utils import get_logger

        logger = get_logger(__name__)
        logger.critical("Initiating application exit due to complete output failure.")

        # Reset the failure counter for next restart
        OutputModule._global_failure_count = 0

        # Don't exit if running in GUI mode - let user see the error
        if OutputModule._gui_mode:
            logger.warning("GUI mode active - not exiting. Please check configuration.")
            return

        # Exit with code 1 to indicate an error condition
        # This should trigger a restart if running under a process supervisor
        os._exit(1)

    @classmethod
    def reset_failure_count(cls) -> None:
        """
        Reset the global failure counter.
        Should be called when any output module successfully transmits data.
        """
        cls._global_failure_count = 0

    @classmethod
    def get_global_topic_store(cls) -> TopicStore:
        """
        Get the class-level shared TopicStore that aggregates
        messages from all output module instances.

        Returns:
            TopicStore: The shared global topic store.
        """
        return cls._global_topic_store

    def set_fallback(self, fallback: "OutputModule") -> None:
        """
        Set a new fallback module.

        Args:
            fallback (OutputModule): The fallback output module.

        Raises:
            AdapterLogicError: If fallback is not a valid OutputModule.
        """
        if not isinstance(fallback, OutputModule):
            self._handle_exception(AdapterLogicError("Can't set fallback to a non-output module."))
        else:
            self._fallback = fallback

    def add_parallel(self, parallel: "OutputModule") -> None:
        """
        Add a parallel output module that receives data simultaneously.

        Unlike fallback (which is only used on failure), parallel outputs
        always receive the data when transmit is called on the primary.

        Args:
            parallel (OutputModule): The parallel output module to add.

        Raises:
            AdapterLogicError: If parallel is not a valid OutputModule.
        """
        if not isinstance(parallel, OutputModule):
            self._handle_exception(AdapterLogicError("Can't add parallel that is not an OutputModule."))
        else:
            self._parallels.append(parallel)

    def transmit_to_parallels(self, topic: str, data: str) -> None:
        """
        Transmit data to all parallel output modules.

        This is a best-effort operation - failures in parallel outputs
        are logged but do not affect the primary transmission result.
        Subclasses should call this after successful primary transmission.

        Args:
            topic (str): The topic or destination identifier.
            data (str): Serialized data to be transmitted.
        """
        for parallel in self._parallels:
            try:
                parallel.transmit(topic, data)
            except Exception as e:
                from leaf.utility.logger.logger_utils import get_logger

                logger = get_logger(__name__)
                logger.warning(f"Parallel output {parallel.__class__.__name__} failed: {e}")

    def is_enabled(self) -> bool:
        """
        Check whether output is enabled.

        Returns:
            bool: True if enabled, False otherwise.
        """
        return self._enabled is None

    def get_disabled_time(self) -> float | None:
        """
        Get the timestamp when the output was disabled.

        Returns:
            Optional[float]: Timestamp, or None if not disabled.
        """
        return self._enabled

    def enable(self) -> None:
        """
        Re-enable output transmission.
        """
        self._enabled = None

    def disable(self) -> None:
        """
        Disable output transmission to prevent data dispatch.
        """
        self._enabled = time.time()

    def pop_all_messages(self) -> Any:
        """
        Yield all messages currently held by the module and its fallback.

        Yields:
            Any: Stored messages one at a time.
        """
        while True:
            message = self.pop()
            if message is None:
                break
            yield message

        if self._fallback is not None:
            yield from self._fallback.pop_all_messages()

    def _handle_exception(self, exception: LEAFError) -> None:
        """
        Handle exceptions by forwarding to the error holder or raising.

        Args:
            exception (LEAFError): Error to be reported or raised.
        """
        if self._error_holder is not None:
            self._error_holder.add_error(exception)
        else:
            raise exception

    def store_latest(self, topic: str, message: Any) -> None:
        """
        Store the latest message for a topic in both the
        per-instance store and the class-level global store.

        Args:
            topic (str): The hierarchical topic string.
            message (Any): The message to store.
        """
        self._topic_store.set(topic, message)
        OutputModule._global_topic_store.set(f"{self.name}/{topic}", message)

    def get_latest(self, topic: str) -> Any:
        """
        Get the latest message stored for a topic.

        Args:
            topic (str): The hierarchical topic string.

        Returns:
            Any: The latest message, or None if no message stored.
        """
        return self._topic_store.get(topic)

    def get_topic_store(self) -> TopicStore:
        """
        Get the topic store instance for this output module.

        Returns:
            TopicStore: The topic store.
        """
        return self._topic_store

    @property
    def name(self) -> str:
        """
        Human-readable name identifying this module instance.
        Returns the explicit name if set, otherwise the class name.
        Subclasses should set ``self._name`` to a config-derived
        default (e.g. ``MQTT(broker:port)``) when no explicit name
        is provided.

        Returns:
            str: The module instance name.
        """
        return self._name if self._name else self.__class__.__name__
