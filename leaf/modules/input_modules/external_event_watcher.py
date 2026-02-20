from collections.abc import Callable

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


class ExternalEventWatcher(EventWatcher):
    def __init__(
        self,
        metadata_manager: MetadataManager = None,
        callbacks: list[Callable] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        super().__init__(metadata_manager, callbacks=callbacks, error_holder=error_holder)
