from enum import Enum
from typing import Any


class SeverityLevel(Enum):
    INFO = 1  # Informational, log only
    WARNING = 2  # Warning, may need attention
    ERROR = 3  # Recoverable error, retry or fallback
    CRITICAL = 4  # Critical, may require immediate action or recovery


class LEAFError(Exception):
    """Base class for other exceptions"""

    def __init__(self, message: str, severity: SeverityLevel):
        self._severity = severity
        self._message = message
        super().__init__(message)

    @property
    def severity(self) -> SeverityLevel:
        """Return the severity of the error."""
        return self._severity

    def to_json(self):
        return {"type": self.__class__.__name__, "severity": str(self._severity), "message": self._message}

    def upgrade_severity(self) -> None:
        """
        Upgrade the severity of the error to the next level.
        """
        upgr_sev = self._next_severity_level(self.severity)
        if upgr_sev != self.severity:
            self._severity = upgr_sev

    def _next_severity_level(self, current_severity: SeverityLevel) -> SeverityLevel:
        """
        Calculate the next severity level, capping at CRITICAL.

        Args:
            current_severity (SeverityLevel): The current severity level.

        Returns:
            SeverityLevel: The next severity level.
        """

        next_value = min(current_severity.value + 1, SeverityLevel.CRITICAL.value)
        return SeverityLevel(next_value)

    def __str__(self) -> str:
        return f"{self._message} - {self.__class__.__name__} - {self.severity}"

    def __eq__(self, value):
        if not isinstance(value, LEAFError):
            return False
        return self._message == value._message and self.severity == value.severity


class InputError(LEAFError):
    """
    Either the hardware is down, or the input mechanism
    cannot access the information it should be able to.
    """

    def __init__(self, reason: str, severity: SeverityLevel = SeverityLevel.ERROR):
        message = f"Can't access InputData: {reason}."
        super().__init__(message, severity)


class HardwareStalledError(LEAFError):
    """
    The hardware appears to have stopped transmitting information.
    """

    def __init__(self, reason: str, severity: SeverityLevel = SeverityLevel.WARNING):
        message = f"Hardware may have stalled: {reason}."
        super().__init__(message, severity)


class ClientUnreachableError(LEAFError):
    """
    The client OR output mechanism can't post information.
    For example, the MQTT broker can't be transmitted to.
    """

    def __init__(self, reason: str, output_module: Any = None, severity: SeverityLevel = SeverityLevel.WARNING):
        message = f"Cannot connect or reach client: {reason}."
        super().__init__(message, severity)
        self.client = output_module


class AdapterBuildError(LEAFError):
    """
    An error occurs when the adapter is being built.
    """

    def __init__(self, reason: str, severity: SeverityLevel = SeverityLevel.CRITICAL) -> None:
        message = f"Adapter configuring is invalid: {reason}."
        super().__init__(message, severity)


class AdapterLogicError(LEAFError):
    """
    Logic within how the adapter has been built causes an error.
    """

    def __init__(self, reason: str, severity: SeverityLevel = SeverityLevel.WARNING) -> None:
        message = f"How the adapter has been built has caused an error: {reason}."
        super().__init__(message, severity)


class InterpreterError(LEAFError):
    """
    The adapter interpreter has some faults that
    cannot be identified without knowledge of the adapter's specifics.
    """

    def __init__(self, reason: str, severity: SeverityLevel = SeverityLevel.INFO):
        message = f"Error within the interpreter: {reason}."
        super().__init__(message, severity)
