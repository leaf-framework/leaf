from abc import ABC, abstractmethod


class MeasurementModule(ABC):
    """
    Abstract class that defines the structure for measurement adapters.
    Take in ambiguous representations of specific
    measurements (e.g., O2, pH) from equipment and return a
    uniform measurement in specific units using agreed-upon terms.
    """

    def __init__(self, term: str) -> None:
        """
        Initialise the MeasurementModule with a
        specific measurement term.

        Args:
            term: The term representing the
            type of measurement (e.g., O2, pH).
        """
        self._term = term

    @property
    def term(self) -> str:
        """
        The measurement term.

        Returns:
            The term associated with the measurement (e.g., O2, pH).
        """
        return self._term

    @abstractmethod
    def transform(self, measurement) -> None:
        """
        Abstract method to transform an
        ambiguous measurement into a standardised form.

        Args:
            measurement: The raw measurement data to be transformed.

        Returns:
            A standardised measurement based
            on the defined transformation logic.
        """
        pass
