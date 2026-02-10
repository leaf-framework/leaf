import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.measurement_handler.terms import measurement_manager
from leaf.modules.measurement_modules.measurement_module import MeasurementModule
from leaf.modules.measurement_modules.ph import pH

logging.basicConfig(level=logging.DEBUG)


class TestMeasurementManager(unittest.TestCase):
    def setUp(self):
        pass

    def test_map_classes(self):
        ph_adapter = measurement_manager.pH
        self.assertIsInstance(ph_adapter, pH)

    def test_all_measurement(self):
        for key in measurement_manager.measurements_data.keys():
            measurement = getattr(measurement_manager, key)
            self.assertIsInstance(measurement, MeasurementModule)


if __name__ == "__main__":
    unittest.main()
