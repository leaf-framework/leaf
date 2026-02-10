from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class Temperature(MeasurementModule):
    """
    Adapter class for handling Temperature measurements.
    Inherits from the abstract MeasurementModule class.
    It takes raw Temperature measurement data and returns it
    in a standardised form.
    """

    def __init__(self, term):
        """
        Initialise the Temperature adapter with the
        term representing the measurement type from the
        measurement_manager.

        Args:
            term: The term representing the measurement
            (e.g., "Temperature").
        """
        super().__init__(term)

    def transform(self, measurement):
        """
        Transform the raw Temperature measurement data
        into a standard form.

        Args:
            measurement: The raw measurement data for Temperature.

        Returns:
            The processed measurement.
        """
        return measurement
