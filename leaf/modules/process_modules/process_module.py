import time
from typing import TYPE_CHECKING, Any

from leaf_register.metadata import MetadataManager
from leaf_register.topic_utilities import topic_utilities

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.phase import PhaseModule

if TYPE_CHECKING:
    from leaf.adapters.equipment_adapter import AbstractInterpreter


class ProcessModule:
    """
    A container for managing and running a specific process
    within an EquipmentAdapter. A ProcessModule may consist
    of multiple PhaseModules, each controlling a particular
    phase of the process and enabling grouping multiple phases
    under one process for better organization and execution.
    """

    def __init__(
        self,
        output: OutputModule,
        phases: list[PhaseModule],
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ):
        """
        Initialise the ProcessModule with a collection of phases.

        Args:
            output (OutputModule): The output mechanism for transmitting data.
            phases (list[PhaseModule]): A list of PhaseModules that represent
                          different phases of the process.
            metadata_manager (Optional[MetadataManager]): An optional manager for process metadata.
            error_holder (Optional[ErrorHolder]): An optional error holder for managing process errors.
        """
        if not isinstance(phases, (list, set, tuple)):
            phases = [phases]
        self._output = output
        self._phases = phases
        self._error_holder = error_holder
        self._metadata_manager = metadata_manager

    def transmit_error(self, error: dict) -> None:
        error_topic = self._metadata_manager.error()
        self._output.transmit(error_topic, error)

    def withdraw(self) -> None:
        """
        Stop all phases by flushing their respective terms if they are complete.
        """
        for phase in self._phases:
            term = phase.get_term()
            if topic_utilities.is_complete_topic(term):
                self._output.flush(term)
                time.sleep(0.1)

    def stop(self) -> None:
        """
        Disconnects the attached output module.
        """
        self._output.disconnect()

    def process_input(self, topic: Any, data: dict) -> None:
        """
        Process input data by passing it to the appropriate phase.

        Args:
            topic (str): The topic to activate a specific phase.
            data (dict): The data to be processed by the phase.
        """
        for phase in self._phases:
            if phase.is_activated(topic):
                phase_data = phase.update(data)
                if phase_data is None:
                    continue
                for topic_val, data in phase_data:
                    if data is None:
                        continue
                    self._output.transmit(topic_val, data)

    def set_interpreter(self, interpreter: "AbstractInterpreter") -> None:
        """
        Set or update the interpreter for all phases within the process.

        Args:
            interpreter (AbstractInterpreter): The interpreter to be set for each PhaseModule.
        """
        for phase in self._phases:
            phase.set_interpreter(interpreter)

    def set_error_holder(self, error_holder: ErrorHolder) -> None:
        """
        Set or update the error holder for managing process errors.

        Args:
            error_holder (ErrorHolder): The error holder to be set for the process and phases.
        """
        self._error_holder = error_holder
        for phase in self._phases:
            phase.set_error_holder(error_holder)

    def set_metadata_manager(self, manager: MetadataManager) -> None:
        """
        Set or update the metadata manager for the process and its phases.

        Args:
            manager (MetadataManager): The metadata manager to be set.
        """
        self._metadata_manager = manager
        [p.set_metadata_manager(manager) for p in self._phases]

    def get_phase_terms(self) -> set[str]:
        """
        Return the set of topic terms associated with each phase.

        Returns:
            set[str]: A set of terms each phase listens to or handles.
        """
        return {phase.get_term() for phase in self._phases}
