from typing import Any

from leaf.adapters.equipment_adapter import AbstractInterpreter, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.error import ErrorPhase
from leaf.modules.phase_modules.initialisation import InitialisationPhase
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.phase_modules.start import StartPhase
from leaf.modules.phase_modules.stop import StopPhase
from leaf.modules.process_modules.discrete_module import DiscreteProcess
from leaf.register.metadata import MetadataManager


class DiscreteExperimentAdapter(EquipmentAdapter):
    """
    Adapter that implements a discrete start-stop process workflow.

    It sets up individual phases for start, stop, measure, and details.
    The process is triggered by incoming events, not continuous monitoring.
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
        Initialise the DiscreteExperimentAdapter.

        Args:
            instance_data (dict): Configuration and instance-level metadata.
            watcher (EventWatcher): Monitors input events to trigger phase execution.
            output (OutputModule): Module to transmit processed data externally.
            interpreter (AbstractInterpreter): Translates raw data into structured output.
            maximum_message_size (Optional[int]): Max batch size for messages in MeasurePhase.
            error_holder (Optional[ErrorHolder]): Shared error container.
            metadata_manager (Optional[MetadataManager]): Optional metadata manager.
            experiment_timeout (Optional[int]): Max time allowed between measurements.
            external_watcher (Optional[ExternalEventWatcher]): Input for out-of-band events (optional).
        """
        # Initialize phase modules
        start_p = StartPhase(metadata_manager)
        stop_p = StopPhase(metadata_manager)
        measure_p = MeasurePhase(metadata_manager, maximum_message_size=maximum_message_size)
        details_p = InitialisationPhase(metadata_manager)
        error_p = ErrorPhase(metadata_manager)

        # Combine into a discrete process
        phases = [start_p, measure_p, stop_p, details_p, error_p]
        processes = [DiscreteProcess(output, phases)]

        super().__init__(
            instance_data,
            watcher,
            output,
            processes,
            interpreter,
            metadata_manager=metadata_manager,
            error_holder=error_holder,
            experiment_timeout=experiment_timeout,
            external_watcher=external_watcher,
        )
