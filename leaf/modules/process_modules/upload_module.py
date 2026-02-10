import time

from leaf_register.metadata import MetadataManager

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.modules.process_modules.discrete_module import DiscreteProcess


class UploadProcess(DiscreteProcess):
    """
    A UploadProcess for processes with multiple phases.
    This process activates phases based on artificial actions.
    This process is for cases where data is provided in retrospect,
    such as when equipment doesn't express data until the end of
    an experiment or requires retroactive user manipulation.
    """

    def __init__(
        self,
        output: OutputModule,
        phases: list[PhaseModule],
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ):
        """
        Initialise the UploadProcess with multiple phases.

        Args:
            output (OutputModule): The output mechanism for transmitting data.
            phases (list[PhaseModule]): A collection of PhaseModules representing
                          the different phases of the discrete process.
            metadata_manager (Optional[MetadataManager]): An optional manager for process metadata.
            error_holder (Optional[ErrorHolder]): An optional error holder for managing process errors.
        """
        super().__init__(output, phases, metadata_manager=metadata_manager, error_holder=error_holder)

    def process_input(self, topic: str, data: dict):
        """
        Dispatches phases based on artifical actions (start,measurement and stop.)
        Process input data by passing it to the appropriate phase.
        Args:
            topic (str): The topic to activate a specific phase.
            data (dict): The data to be processed by the phase.
        """
        if topic() != self._metadata_manager.experiment.start():
            assert topic() == self._metadata_manager.details()
            return super().process_input(topic, data)

        # Start
        super().process_input(topic, data)
        time.sleep(1)

        # Measurements
        measure_builder = self._metadata_manager.experiment.measurement
        super().process_input(measure_builder, data)
        time.sleep(1)

        # Stop
        stop_builder = self._metadata_manager.experiment.stop
        super().process_input(stop_builder, data)
        time.sleep(1)
