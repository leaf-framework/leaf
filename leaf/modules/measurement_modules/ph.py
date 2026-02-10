from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class pH(MeasurementModule):
    """
    Adapter class for handling pH measurements.
    Inherits from the abstract MeasurementModule class.
    It takes raw pH measurement data and returns it in
    a standardised form.
    """

    def __init__(self, term):
        """
        Initialise the pH adapter with the
        term representing the measurement type from the
        measurement_manager.

        Args:
            term: The term representing the measurement (e.g., "pH").
        """
        super().__init__(term)

    def transform(self, measurement):
        """
        Transform the raw pH measurement data into a standard form.

        Args:
            measurement: The raw measurement data for pH.

        Returns:
            The processed measurement.
        """
        return measurement
