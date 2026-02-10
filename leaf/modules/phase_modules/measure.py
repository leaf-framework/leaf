import time
from typing import Any

from influxobject import InfluxPoint
from leaf_register.metadata import MetadataManager

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterLogicError, InterpreterError
from leaf.modules.phase_modules.phase import PhaseModule
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="measure.log")


class MeasurePhase(PhaseModule):
    """
    Handles the measurement-related actions within a process.
    It transmits measurement data.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager | None = None,
        maximum_message_size: int = 1,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the MeasurePhase with metadata manager and optional maximum_message_size setting.

        Args:
            metadata_manager (Optional[MetadataManager]): Manages metadata associated with the phase.
            maximum_message_size (Optional[int]): The maximum number of measurements in a single message.
            error_holder (Optional[ErrorHolder]): Optional, an error holder to manage phase errors.
        """
        term_builder = (
            metadata_manager.experiment.measurement
            if metadata_manager is not None
            else "metadata_manager.experiment.measurement"
        )

        super().__init__(term_builder, metadata_manager=metadata_manager, error_holder=error_holder)
        self._maximum_message_size: int = maximum_message_size

    def update(self, data: Any | None = None, **kwargs: Any) -> list[tuple[str, Any]] | None:
        """
        Called to process new measurements and transmit the data.

        Args:
            data (Optional[Any]): Data to be transmitted.
            **kwargs (Any): Additional arguments used to build the action term.

        Returns:
            Optional[list]: A list of messages or None if an error occurs.
        """
        if data is None:
            excp = AdapterLogicError("Measurement system activated without any data")
            self._handle_exception(excp)
            return None

        if self._interpreter is not None:
            if getattr(self._interpreter, "id", None) is None:
                logger.warning("Interpreter has no experiment id set.")
                self._interpreter.id = "invalid_id"
            exp_id = self._interpreter.id
            if exp_id is None:
                excp = AdapterLogicError("Trying to transmit measurements outside of experiment (No experiment id)")
                self._handle_exception(excp)

            try:
                result = self._interpreter.measurement(data)
            except Exception as ex:
                leaf_exp = InterpreterError(ex)
                self._handle_exception(leaf_exp)
                return None

            if result is False:
                # Case when the interpreter
                # doesnt want to send a message.
                return None

            if result is None:
                excp = AdapterLogicError(
                    "Interpreter couldn't parse measurement, likely metadata has been provided as measurement data."
                )
                self._handle_exception(excp)
                return None
            if isinstance(result, (set, list, tuple)):
                result = list(result)
                chunks = [
                    result[i : i + self._maximum_message_size]
                    for i in range(0, len(result), self._maximum_message_size)
                ]
                messages = []
                for index, chunk in enumerate(chunks):
                    if index % 10 == 0:
                        logger.debug(f"Sending chunk {index + 1} of {len(chunks)} with {len(chunk)} measurements.")
                    messages.append(self._form_message(exp_id, chunk))
                    time.sleep(0.1)
                return messages
            else:
                return [self._form_message(exp_id, result)]
        else:
            experiment_id = kwargs.get("experiment_id", "unknown")
            measurement = kwargs.get("measurement", "unknown")

            action = self._term_builder(experiment_id=experiment_id, measurement=measurement)
            return [(action, data)]

    def _form_message(self, experiment_id: str, result: Any) -> tuple:
        """
        Formulate a message with the experiment ID and result.

        Args:
            experiment_id (str): The ID of the experiment.
            result (Any): The measurement result data.

        Returns:
            tuple: A tuple containing the action and result.
        """
        measurement = "unknown"
        if isinstance(result, dict):
            measurement = result.get("measurement", "unknown")
        elif isinstance(result, InfluxPoint):
            result = result.to_json()
            measurement = result.get("measurement", "unknown")
        elif isinstance(result, list):
            result = [l.to_json() if isinstance(l, InfluxPoint) else l for l in result]
        else:
            excp = AdapterLogicError(f"Unknown measurement data type: {type(result)}")
            self._handle_exception(excp)

        action = self._term_builder(experiment_id=experiment_id, measurement=measurement)
        return (action, result)
