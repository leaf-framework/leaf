from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class CarbonDioxide(MeasurementModule):
    """
    Adapter class for handling Carbon Dioxide (CO2) measurements.
    Inherits from the abstract MeasurementModule class. It takes raw CO2
    measurement data and returns it in a standardised form.
    """

    def __init__(self, term):
        """
        Initialise the CarbonDioxide adapter with the
        term representing the measurement type from the
        measurement_manager.

        Args:
            term: The term representing the measurement (e.g., "CO2").
        """
        super().__init__(term)

    def transform(self, measurement):
        """
        Transform the raw CO2 measurement data into a standard form.

        Args:
            measurement: The raw measurement data for CO2.

        Returns:
            The processed measurement.
        """
        return measurement
