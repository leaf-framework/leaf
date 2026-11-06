from typing import Any

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import InterpreterError
from leaf.modules.phase_modules.control import ControlPhase
from leaf.register.metadata import MetadataManager


class StopPhase(ControlPhase):
    """
    A ControlPhase responsible for stopping the process by building
    the necessary actions and setting the running status.
    Inherits from ControlPhase.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the StopPhase with metadata manager and error holder.

        Args:
            metadata_manager (MetadataManager): Manages metadata associated with the phase.
            error_holder (Optional[ErrorHolder]): Optional, an error holder to manage phase errors.
        """
        term_builder = metadata_manager.stop
        super().__init__(term_builder, metadata_manager=metadata_manager, error_holder=error_holder)

    def update(self, data: Any) -> list:
        """
        Update the StopPhase by transmitting actions to set the equipment as stopped.

        Args:
            data (Any): Data to be transmitted.

        Returns:
            list: A list of tuples containing the action terms and data.
        """
        # Leaving unused until stop experiment metadata is agreed upon.
        if self._interpreter is not None:
            try:
                data = self._interpreter.experiment_stop(data)
            except Exception as ex:
                leaf_exp = InterpreterError(ex)
                self._handle_exception(leaf_exp)
        data = super().update(data)
        data += [(self._metadata_manager.running(), False)]
        data += [(self._metadata_manager.start(), None)]
        return data
