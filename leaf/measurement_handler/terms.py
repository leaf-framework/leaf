import importlib
import inspect
import os
from typing import Any

import yaml

from leaf.modules.measurement_modules.measurement_module import MeasurementModule


class MeasurementManager:
    """
    Singleton class that holds the measurement mapping
    and lazily initializes specific measurement instances.
    """

    _instance = None

    def __new__(cls, *args, **kwargs) -> "MeasurementManager":
        if cls._instance is None:
            cls._instance = super(MeasurementManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, file_path=None) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True
            if file_path is None:
                file_path = os.path.join(os.path.dirname(__file__), "measurements.yaml")
            self.measurements_data = self._load_measurements(file_path)
            self._measurement_instances = {}

    def _load_measurements(self, file_path):
        """Load the measurement data from the YAML file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file '{file_path}' was not found.")

        with open(file_path) as file:
            return yaml.safe_load(file)

    def __getattr__(self, key):
        """
        Lazy-load the measurement when accessed.
        """
        if key in ["measurements_data", "_measurement_instances", "_initialized"]:
            raise AttributeError(f"Attribute '{key}' not found.")

        if key in self.measurements_data:
            if key not in self._measurement_instances:
                class_name = self.measurements_data[key]
                self._measurement_instances[key] = self._load_class(key, class_name)
            return self._measurement_instances[key]
        else:
            raise AttributeError(f"Measurement '{key}' not found.")

    def _load_class(self, key, class_name):
        """
        Dynamically load the measurement class from the appropriate
        module and find the class that inherits from the Measurement
        base class.
        """
        module_name = f"leaf.modules.measurement_modules.{class_name.lower()}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            raise NotImplementedError(f"Module for {class_name} not implemented.")

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, MeasurementModule) and obj is not MeasurementModule:
                measurement_class = obj
                break
        else:
            raise ImportError(f"No class derived from Measurement found in module {module_name}")

        return measurement_class(term=key)

    def get_measurements(self, keys=None) -> dict[str, Any]:
        """
        Takes a list of measurement names and returns a dictionary
        of the corresponding Measurement objects.
        """
        if keys is None:
            keys = self.measurements_data
        measurements = {}
        for key in keys:
            try:
                measurements[key] = getattr(self, key)
            except AttributeError:
                raise NotImplementedError(f"Module for {key} not implemented.")
        return measurements


measurement_manager: MeasurementManager = MeasurementManager()
