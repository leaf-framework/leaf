from leaf_register.metadata import MetadataManager

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.modules.process_modules.process_module import ProcessModule


class DiscreteProcess(ProcessModule):
    """
    A ProcessModule for processes with multiple phases.
    In a discrete process, there are distinct phases,
    such as start, measurement, and stop phases.
    Discrete processes do not actually set the phase in
    any way but are collections for I/O actions.
    """

    def __init__(
        self,
        output: OutputModule,
        phases: list[PhaseModule],
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ):
        """
        Initialize the DiscreteProcess with multiple phases.

        Args:
            output (OutputModule): The output mechanism for transmitting data.
            phases (list[PhaseModule]): A collection of PhaseModules representing
                          the different phases of the discrete process.
            metadata_manager (Optional[MetadataManager]): An optional manager for process metadata.
            error_holder (Optional[ErrorHolder]): An optional error holder for managing process errors.

        Raises:
            AdapterBuildError: If only one phase is provided.
                              Use ContinuousProcess instead.
        """
        if not isinstance(phases, (list, tuple, set)) or len(phases) <= 1:
            raise AdapterBuildError("Discrete process should have more than one phase. Use continuous process instead.")
        super().__init__(output, phases, metadata_manager=metadata_manager, error_holder=error_holder)
