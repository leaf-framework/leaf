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
from leaf.modules.process_modules.continous_module import ContinousProcess
from leaf.modules.process_modules.process_module import ProcessModule
from leaf.register.metadata import MetadataManager


class ContinuousExperimentAdapter(EquipmentAdapter):
    """
    Adapter that implements a continuous process workflow for equipment
    without defined experiment start/stop boundaries.

    It runs the measurement process continuously and wraps start/stop/details
    in a parallel control process.
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
        Initialise the ContinuousExperimentAdapter.

        Args:
            instance_data (dict): Configuration and metadata for this adapter.
            watcher (EventWatcher): Input module that monitors raw data/events.
            output (OutputModule): Output module to transmit processed data.
            interpreter (AbstractInterpreter): Parses and transforms raw inputs.
            maximum_message_size (Optional[int]): Limit for batching measurement messages.
            error_holder (Optional[ErrorHolder]): Shared error collector.
            metadata_manager (Optional[MetadataManager]): Metadata manager instance.
            experiment_timeout (Optional[int]): Optional timeout between measurements.
            external_watcher (Optional[ExternalEventWatcher]): Optional external input module.
        """
        # Initialize phases
        start_p = StartPhase(metadata_manager)
        stop_p = StopPhase(metadata_manager)
        measure_p = MeasurePhase(metadata_manager, maximum_message_size=maximum_message_size)
        details_p = InitialisationPhase(metadata_manager)
        error_p = ErrorPhase(metadata_manager)

        # Set up continuous and control processes
        measurement_process = ContinousProcess(
            output, measure_p, metadata_manager=metadata_manager, error_holder=error_holder
        )

        self._control_process = ProcessModule(
            output, [start_p, stop_p, details_p, error_p], metadata_manager=metadata_manager, error_holder=error_holder
        )

        processes = [measurement_process, self._control_process]

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

    def start(self) -> None:
        """
        Trigger the start phase and launch the adapter loop.

        Injects a synthetic start message via the control process
        to initialise any start-specific logic or output.
        """
        start_topic = self._metadata_manager.experiment.start
        self._control_process.process_input(start_topic, {})
        super().start()
