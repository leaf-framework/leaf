from typing import Any

from leaf_register.metadata import MetadataManager

from leaf.adapters.equipment_adapter import AbstractInterpreter, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.initialisation import InitialisationPhase
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.phase_modules.start import StartPhase
from leaf.modules.phase_modules.stop import StopPhase
from leaf.modules.process_modules.upload_module import UploadProcess


class UploadAdapter(EquipmentAdapter):
    """
    Adapter for equipment that stores data to a file all at once,
    or where data must be manually uploaded into a watched directory.

    This adapter uses a file watcher to detect new uploads and processes
    the data through an artificial start-measure-stop sequence.
    """

    def __init__(
        self,
        instance_data: dict[str, Any],
        output: OutputModule,
        interpreter: AbstractInterpreter,
        watch_dir: str | None = None,
        maximum_message_size: int | None = 1,
        error_holder: ErrorHolder | None = None,
        metadata_manager: MetadataManager | None = None,
        experiment_timeout: int | None = None,
        external_watcher: ExternalEventWatcher | None = None,
    ):
        """
        Initialise the UploadAdapter.

        Args:
            instance_data (dict): Instance-level configuration and metadata.
            output (OutputModule): The output module used to transmit parsed data.
            interpreter (AbstractInterpreter): Parses and translates raw data.
            watch_dir (Optional[str]): Directory path to monitor for uploaded files.
            maximum_message_size (Optional[int]): Max number of messages per transmission.
            error_holder (Optional[ErrorHolder]): Error tracking object.
            metadata_manager (Optional[MetadataManager]): Optional metadata manager.
            experiment_timeout (Optional[int]): Timeout between measurements (not used here).
            external_watcher (Optional[ExternalEventWatcher]): Optional listener for external inputs.
        """
        # Input module: watches a local directory
        watcher = FileWatcher(watch_dir, metadata_manager, error_holder=error_holder)

        # Initialize discrete phases
        start_p = StartPhase(metadata_manager)
        stop_p = StopPhase(metadata_manager)
        measure_p = MeasurePhase(metadata_manager, maximum_message_size=maximum_message_size)
        details_p = InitialisationPhase(metadata_manager)

        # Combine phases into a process
        phases = [start_p, measure_p, stop_p, details_p]
        processes = [UploadProcess(output, phases)]

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
