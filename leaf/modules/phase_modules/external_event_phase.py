from datetime import datetime
from typing import Any

from leaf_register.metadata import MetadataManager

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="external_events.log")


class ExternalEventPhase(PhaseModule):
    def __init__(
        self, metadata_manager: MetadataManager | None = None, error_holder: ErrorHolder | None = None
    ) -> None:
        # Could we add something to the register?
        term_builder = None  # self._metadata_manager.external_input
        super().__init__(term_builder, metadata_manager=metadata_manager, error_holder=error_holder)

    def update(self, topic: str, data: Any | None = None) -> list | None:
        if hasattr(self._interpreter, "external_input"):
            res = self._interpreter.external_input(data)
        else:
            res = None
        action_dict = {"topic": topic, "data": data, "actions_taken": res, "timestamp": datetime.now().isoformat()}
        logger.info(f"{action_dict}")
