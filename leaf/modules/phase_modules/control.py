from collections.abc import Callable
from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.register.metadata import MetadataManager


class ControlPhase(PhaseModule):
    """
    Handles control-related phases in a process.
    Inherits from PhaseModule, allowing custom behavior for
    controlling equipment during different phases such as
    initialization or stopping.
    """

    def __init__(
        self,
        phase_term: Callable | str,
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the ControlPhase with the phase term and metadata manager.

        Args:
            phase_term (str): The term representing the control phase action.
            metadata_manager (Optional[MetadataManager]): Manages metadata associated with the phase.
            error_holder (Optional[ErrorHolder]): Optional, an error holder to manage phase errors.
        """
        super().__init__(phase_term, metadata_manager=metadata_manager, error_holder=error_holder)

    def update(self, data: Any | None = None, **kwargs: Any) -> list:
        """
        Builds the control phase term.

        Args:
            data (Optional[Any]): Data associated with the control phase.
            **kwargs (Any): Additional arguments to build the action term.

        Returns:
            list: A list of tuples containing the action term and data.
        """
        return super().update(data=data, **kwargs)
