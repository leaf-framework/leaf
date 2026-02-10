import os

from leaf_register.metadata import MetadataManager

from leaf.adapters.core_adapters.discrete_experiment_adapter import DiscreteExperimentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.modules.output_modules.output_module import OutputModule
from tests.generic_adapter.interpreter import MockInterpreter

current_dir = os.path.dirname(os.path.abspath(__file__))
metadata_fn = os.path.join(current_dir, "device.json")


class GenericDiscreteAdapter(DiscreteExperimentAdapter):
    def __init__(
        self,
        instance_data: dict[str, str],
        input_class: EventWatcher,
        input_params: dict,
        output: OutputModule,
        interpreter=None,
        maximum_message_size: int | None = 1,
        error_holder: ErrorHolder | None = None,
        experiment_timeout: int | None = None,
        external_watcher: ExternalEventWatcher = None,
        **kwargs,
    ):
        if interpreter is None:
            interpreter = MockInterpreter()
        metadata_manager = MetadataManager()
        watcher = input_class(metadata_manager, **input_params)
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
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._metadata_manager.add_equipment_data(metadata_fn)
