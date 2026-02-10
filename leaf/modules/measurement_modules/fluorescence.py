from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class Fluorescence(MeasurementModule):
    """
    Adapter class for handling Fluorescence measurements.
    Inherits from the abstract MeasurementModule class.
    It takes raw Fluorescence measurement data and
    returns it in a standardised form.
    """

    def __init__(self, term):
        """
        Initialise the Fluorescence adapter with the
        term representing the measurement type from the
        measurement_manager.

        Args:
            term: The term representing the measurement
            (e.g., "Fluorescence").
        """
        super().__init__(term)

    def transform(self, measurement):
        """
        Transform the raw Fluorescence measurement data into a
        standard form.

        Args:
            measurement: The raw measurement data for Fluorescence.

        Returns:
            The processed measurement.
        """
        return measurement
