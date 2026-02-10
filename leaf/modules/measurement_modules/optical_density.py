from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class OpticalDensity(MeasurementModule):
    """
    Adapter class for handling Optical Density (OD) measurements.
    Inherits from the abstract MeasurementModule class. It takes raw OD
    measurement data and returns it in a standardized form.
    """

    def __init__(self, term):
        """
        Initialize the OpticalDensity adapter with the
        term representing the measurement type from the
        measurement_manager.

        Args:
            term: The term representing the measurement (e.g., "OD").
        """
        super().__init__(term)

    def transform(self, measurement):
        """
        Transform the raw Optical Density measurement data
        into a standard form.

        Args:
            measurement: The raw measurement data for OD.

        Returns:
            The processed measurement.
        """
        return measurement
