import os

from leaf.adapters.core_adapters.discrete_experiment_adapter import DiscreteExperimentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.modules.output_modules.output_module import OutputModule
from leaf.register.metadata import MetadataManager
from tests.mock_functional_adapter.interpreter import MockInterpreter

current_dir = os.path.dirname(os.path.abspath(__file__))
metadata_fn = os.path.join(current_dir, "device.json")


class MockFunctionalAdapter(DiscreteExperimentAdapter):
    def __init__(
        self,
        instance_data: dict[str, str],
        output: OutputModule,
        write_file: str | None = None,
        maximum_message_size: int | None = 1,
        error_holder: ErrorHolder | None = None,
        experiment_timeout: int | None = None,
        external_watcher: ExternalEventWatcher = None,
    ):
        metadata_manager = MetadataManager()
        directory = os.path.dirname(write_file)  # '/home/user/documents'
        filename = os.path.basename(write_file)  # 'data.csv'
        watcher = FileWatcher(directory, metadata_manager, filenames=filename)
        interpreter = MockInterpreter(error_holder=error_holder)

        super().__init__(
            instance_data,
            watcher,
            output,
            interpreter,
            maximum_message_size=maximum_message_size,
            error_holder=error_holder,
            metadata_manager=metadata_manager,
            experiment_timeout=experiment_timeout,
            external_watcher=external_watcher,
        )
        self._write_file: str | None = write_file
        self._metadata_manager.add_equipment_data(metadata_fn)
