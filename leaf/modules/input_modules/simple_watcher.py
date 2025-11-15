from typing import Optional
from typing import Callable
from typing import List
from typing import Dict
from typing import Any

from leaf_register.metadata import MetadataManager
from leaf.modules.input_modules.polling_watcher import PollingWatcher
from leaf.error_handler.error_holder import ErrorHolder


class SimpleWatcher(PollingWatcher):
    """
    A minimal polling watcher for development and testing.

    Polls at regular intervals and triggers the interpreter's measurement() method.
    Does not fetch data itself - the interpreter handles all data retrieval.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager,
        interval: int,
        callbacks: Optional[List[Callable[[str, Any], None]]] = None,
        error_holder: Optional[ErrorHolder] = None
    ) -> None:
        """
        Initialize the SimpleWatcher.

        Args:
            metadata_manager (MetadataManager): Equipment metadata manager.
            interval (int): Polling interval in seconds.
            callbacks (Optional[List[Callable]]): Callbacks for simulated events.
            error_holder (Optional[ErrorHolder]): Optional error handling instance.
        """
        super().__init__(
            interval=interval,
            metadata_manager=metadata_manager,
            callbacks=callbacks,
            error_holder=error_holder
        )

        self._interval: int = interval
        self._metadata_manager: MetadataManager = metadata_manager

    def _fetch_data(self) -> Dict[str, Optional[dict]]:
        """
        Trigger a measurement poll.

        Returns a dict that triggers the measurement callback. The actual data
        is fetched by the interpreter, so we just return an empty trigger.

        Returns:
            Dict[str, Optional[dict]]: Measurement trigger (content ignored by interpreter).
        """
        return {
            "measurement": {},  # Empty trigger - interpreter fetches real data
            "start": None,
            "stop": None
        }
