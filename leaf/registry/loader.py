import importlib.util
import inspect
from typing import Any

from leaf.adapters.equipment_adapter import EquipmentAdapter
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.registry.utils import inheritance_depth


def load_class_from_file(path: str, class_name: str | None = None, base_class: type = EquipmentAdapter) -> type[Any]:
    """
    Dynamically loads a class from a Python file.

    If `class_name` is provided, attempts to retrieve that class directly.
    If not, searches for the most specific subclass of `base_class` within the file.

    Args:
        path: Full path to the Python file to load.
        class_name: Optional name of the class to load explicitly.
        base_class: The base class that the loaded class must inherit from.

    Returns:
        The loaded class object.

    Raises:
        AdapterBuildError: If the module can't be loaded or no valid class is found.
    """
    spec = importlib.util.spec_from_file_location("module", path)
    if not spec or not spec.loader:
        raise AdapterBuildError(f"Cannot load Python module from {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore
    except Exception as e:
        raise AdapterBuildError(f"Error executing module {path}: {e}") from e

    if class_name:
        if hasattr(module, class_name):
            cls = getattr(module, class_name)
            if inspect.isclass(cls) and issubclass(cls, base_class):
                return cls
            raise AdapterBuildError(f"'{class_name}' is not a subclass of {base_class.__name__}")
        raise AdapterBuildError(f"Class '{class_name}' not found in {path}")

    # No class_name given, so auto-detect the best subclass of base_class
    candidates = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, base_class) and obj is not base_class
    ]

    if not candidates:
        raise AdapterBuildError(f"No subclass of {base_class.__name__} found in {path}")

    # Return the most specific subclass (deepest in the inheritance tree)
    return max(candidates, key=lambda cls: inheritance_depth(cls, base_class))
