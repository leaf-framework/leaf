from leaf_register.metadata import MetadataManager

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.modules.process_modules.process_module import ProcessModule


class ContinousProcess(ProcessModule):
    """
    A ProcessModule for processes with a single phase.
    In a continuous process, there is only one phase that
    runs continuously, such as a measurement or control
    phase that remains active throughout the process.
    """

    def __init__(
        self,
        output: OutputModule,
        phase: PhaseModule,
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ):
        """
        Initialize the ContinousProcess with a single phase.

        Args:
            output (OutputModule): The output mechanism for transmitting data.
            phase (PhaseModule): A single PhaseModule representing the continuous phase.
            metadata_manager (Optional[MetadataManager]): An optional manager for process metadata.
            error_holder (Optional[ErrorHolder]): An optional error holder for managing process errors.

        Raises:
            AdapterBuildError: If more than one phase is provided.
        """
        if not isinstance(phase, PhaseModule):
            raise AdapterBuildError("Continuous process may only have one phase.")
        super().__init__(
            output,
            [phase],
            metadata_manager=metadata_manager,
            error_holder=error_holder,
        )
