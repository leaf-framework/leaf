from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class DissolvedOxygen(MeasurementModule):
    """
    Adapter class for handling Dissolved Oxygen (DO) measurements.
    Inherits from the abstract MeasurementModule class. It takes raw DO
    measurement data and returns it in a standardised form.
    """

    def __init__(self, term):
        """
        Initialise the DissolvedOxygen adapter with the
        term representing the measurement type from the
        measurement_manager.

        Args:
            term: The term representing the measurement (e.g., "DO").
        """
        super().__init__(term)

    def transform(self, measurement):
        """
        Transform the raw Dissolved Oxygen measurement data into
        a standard form.

        Args:
            measurement: The raw measurement data for DO.

        Returns:
            The processed measurement.
        """
        return measurement
