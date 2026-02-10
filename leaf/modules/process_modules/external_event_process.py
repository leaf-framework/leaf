from leaf_register.metadata import MetadataManager

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.external_event_phase import ExternalEventPhase
from leaf.modules.process_modules.process_module import ProcessModule


class ExternalEventProcess(ProcessModule):
    def __init__(
        self,
        output: OutputModule,
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ):
        phase = [ExternalEventPhase(metadata_manager=metadata_manager, error_holder=error_holder)]
        super().__init__(output, phase, metadata_manager=metadata_manager, error_holder=error_holder)

    def process_input(self, topic: str, data: dict) -> None:
        for p in self._phases:
            p.update(topic, data)
