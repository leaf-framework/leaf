from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


class DBWatcher(EventWatcher):
    def __init__(self, metadata_manager: MetadataManager, callbacks=None, error_holder=None):
        raise NotImplementedError()
        term_map = {}
        super().__init__(term_map, metadata_manager, callbacks=callbacks, error_holder=error_holder)

    def start(self):
        raise NotImplementedError()
