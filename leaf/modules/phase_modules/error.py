from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import HardwareStalledError
from leaf.modules.phase_modules.control import ControlPhase
from leaf.register.metadata import MetadataManager


class ErrorPhase(ControlPhase):
    """
    A ControlPhase responsible for processing any errors from the equipment.
    Inherits from ControlPhase.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the ErrorPhase with metadata manager and error holder.

        Args:
            metadata_manager (MetadataManager): Manages metadata associated with the phase.
            error_holder (Optional[ErrorHolder]): Optional, an error holder to manage phase errors.
        """
        term_builder = metadata_manager.error
        super().__init__(term_builder, metadata_manager=metadata_manager, error_holder=error_holder)

    def update(self, data: Any) -> list:
        """
        Update the ErrorPhase by either adding an error to the holder if
        its provided else outputting the message normally.

        Args:
            data (Any): Data to be transmitted.

        Returns:
            list: A list of tuples containing the action
            terms and data or None if the error holder is present.
        """
        error = HardwareStalledError(data)
        if self._error_holder is None:
            data = super().update(error.to_json())
            return data
        else:
            self._handle_exception(error)
            return None
