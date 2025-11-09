from typing import Type, Any, Literal, Dict, List

from leaf.adapters.equipment_adapter import EquipmentAdapter
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.error_handler.exceptions import AdapterBuildError

PluginType = Literal["equipment", "output", "external_input"]

# Internal registry map
_registry: Dict[PluginType, Dict[str, Type[Any]]] = {
    "equipment": {},
    "output": {},
    "external_input": {},
}


def register(plugin_type: PluginType, code: str, cls: Type[Any]) -> None:
    _registry[plugin_type][code.lower()] = cls

def get(plugin_type: PluginType, code: str) -> Type[Any]:
    try:
        return _registry[plugin_type][code.lower()]
    except KeyError:
        raise AdapterBuildError(f"No {plugin_type} class registered for code '{code}'")


def get_equipment_adapter(code: str) -> Type[EquipmentAdapter]:
    """
    Retrieve an EquipmentAdapter class by code.
    """
    cls = get("equipment", code)
    if not issubclass(cls, EquipmentAdapter):
        raise AdapterBuildError(f"'{code}' is not an EquipmentAdapter")
    return cls


def get_output_adapter(code: str) -> Type[OutputModule]:
    """
    Retrieve an OutputModule class by code.
    """
    cls = get("output", code)
    if not issubclass(cls, OutputModule):
        raise AdapterBuildError(f"'{code}' is not an OutputModule")
    return cls


def get_external_input(code: str) -> Type[ExternalEventWatcher]:
    """
    Retrieve an ExternalEventWatcher class by code.
    """
    cls = get("external_input", code)
    if not issubclass(cls, ExternalEventWatcher):
        raise AdapterBuildError(f"'{code}' is not an ExternalEventWatcher")
    return cls


def all_registered(plugin_type: PluginType) -> Dict[str, Type[Any]]:
    """
    Return all registered classes of a given plugin type.
    """
    return dict(_registry[plugin_type])


def discover_from_config(config: dict[str, Any], external_path: str = None) -> None:
    """
    Discover and register only the plugins referenced in the given configuration.
    """
    from leaf.registry import discovery

    output_codes = _collect_output_codes(config.get("OUTPUTS", []))
    equipment_codes = {
        instance["equipment"]["adapter"].lower()
        for instance in config.get("EQUIPMENT_INSTANCES", [])
    }
    ...
    external_input_codes = {
        instance["equipment"]["external_input"]["plugin"].lower()
        for instance in config.get("EQUIPMENT_INSTANCES", [])
        if "external_input" in instance["equipment"]
    }

    discovered_equipment = (
        discovery.discover_entry_point_equipment(equipment_codes)
        + discovery.discover_local_equipment(equipment_codes, [external_path] if external_path else [])
    )
    for code, cls, group in discovered_equipment:
        register("equipment", code, cls)

    # Discover and register outputs
    for code, cls in discovery.discover_output_modules(output_codes):
        register("output", code, cls)

    # Discover and register external inputs
    for code, cls in discovery.discover_external_inputs(external_input_codes):
        register("external_input", code, cls)




def _collect_output_codes(outputs: list[dict]) -> set[str]:
    result = set()

    def recurse(output):
        plugin = output.get("plugin")
        if plugin:
            result.add(plugin.lower())
        fallback = output.get("fallback")
        if isinstance(fallback, dict):
            recurse(fallback)
        elif isinstance(fallback, str):
            result.add(fallback.lower())

    for output in outputs:
        recurse(output)

    return result


def update_equipment_registry(discovered_equipment: list[tuple[str, Type[EquipmentAdapter], Any]]) -> list[str]:
    """
    Update the equipment registry with newly discovered adapters.

    Args:
        discovered_equipment: List of tuples (adapter_id, class, entry_point/group)

    Returns:
        List of newly registered adapter codes
    """
    from leaf.utility.logger.logger_utils import get_logger
    logger = get_logger(__name__)

    newly_registered = []
    for code, cls, group in discovered_equipment:
        code_lower = code.lower()
        if code_lower not in _registry["equipment"]:
            register("equipment", code, cls)
            newly_registered.append(code)
            logger.info(f"Registered new adapter: {code}")
        else:
            # Update existing registration (in case class definition changed)
            register("equipment", code, cls)
            logger.debug(f"Updated existing adapter: {code}")

    return newly_registered


def refresh_equipment_from_discovery() -> list[str]:
    """
    Refresh equipment adapters by re-discovering all available adapters.
    This allows picking up newly installed adapters without restart.

    Returns:
        List of newly registered adapter codes
    """
    from leaf.registry import discovery
    from leaf.utility.logger.logger_utils import get_logger
    logger = get_logger(__name__)

    logger.info("Refreshing equipment adapter registry...")

    # Discover all available equipment adapters (no filter)
    discovered = discovery.discover_entry_point_equipment(needed_codes=None)

    # Update registry with discovered adapters
    newly_registered = update_equipment_registry(discovered)

    logger.info(f"Registry refresh complete. {len(newly_registered)} new adapter(s) registered.")
    return newly_registered