from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.phase_modules.control import ControlPhase
from leaf.register.metadata import MetadataManager


class InitialisationPhase(ControlPhase):
    """
    A phase adapter responsible for handling data when the adapter initializes.
    Inherits from ControlPhase.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the InitialisationPhase with metadata manager and error holder.

        Args:
            metadata_manager (Optional[MetadataManager]): Manages metadata associated with the phase.
            error_holder (Optional[ErrorHolder]): Optional, an error holder to manage phase errors.
        """
        phase_term = metadata_manager.details
        super().__init__(phase_term, metadata_manager=metadata_manager, error_holder=error_holder)

    def update(self, data: Any | None = None) -> list:
        """
        Update the InitialisationPhase by building the initialization topic.

        Args:
            data (Optional[Any]): Data to be transmitted.

        Returns:
            list: A list of tuples containing the action terms and data.
        """
        return super().update(data=data)
