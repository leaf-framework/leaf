import inspect
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

from leaf.adapters.control_spec import apply_limits, read_controls
from leaf.adapters.equipment_adapter import AbstractController, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.output_modules.file import FILE
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.output_module import OutputModule
from leaf.register.topic_utilities import topic_utilities
from leaf.registry.loader import load_class_from_file
from leaf.registry.registry import get_equipment_adapter, get_external_input, get_output_adapter
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.output_group import OutputGroup

logger = get_logger(__name__, log_file="global.log", error_log_file="global_error.log")


def handle_disabled_modules(output: OutputModule, timeout: float) -> None:
    """Attempts to restart the output module if disabled.

    If it can reconnect, all stored messages are output.
    """
    if not output.is_enabled() and time.time() - output.get_disabled_time() > timeout:
        output.connect()
        connect_timeout_count = 0
        connect_timeout = 15
        while not output.is_connected():
            time.sleep(1)
            connect_timeout_count += 1
            if connect_timeout_count > connect_timeout:
                output.disable()
                return
        output.enable()
        thread = threading.Thread(target=output_messages, args=(output,), daemon=True)
        thread.start()


def output_messages(output_module: OutputModule) -> None:
    """Transmits all buffered messages after reconnecting output module."""
    for topic, message in output_module.pop_all_messages():
        output_module.transmit(topic, message)


def get_existing_ids(output_module: OutputModule, time_to_sleep: float = 5.0) -> list[str]:
    """Returns instance IDs of equipment already present in the system."""
    for member in output_module.outputs():
        if isinstance(member, MQTT):
            return _existing_ids(member, time_to_sleep)
    return []


def _existing_ids(output_module: MQTT, time_to_sleep: float) -> list[str]:
    topic = topic_utilities.details()
    logger.debug(f"Setting up subscription to {topic}")
    output_module.subscribe(topic)
    time.sleep(time_to_sleep)
    output_module.unsubscribe(topic)

    ids: list[str] = []
    for k, _ in output_module.messages.items():
        if topic_utilities.is_instance(k, topic):
            ids.append(topic_utilities.parse_topic(k).instance_id)
    output_module.reset_messages()
    return ids


@dataclass
class _Output:
    code: str
    fallback: str | None
    output: OutputModule


def _pop_output_codes(out_data: dict[str, Any]) -> tuple[str, str | None]:
    """Take plugin and fallback out of an OUTPUTS entry, lowercased so "MQTT" and "mqtt" meet."""
    output_code = str(out_data.pop("plugin")).lower()
    fallback = out_data.pop("fallback", None)
    fallback_ref: str | None = None
    if fallback:
        fallback_ref = str(fallback).lower()
    if out_data.pop("parallel", None) is not None:
        logger.warning("'parallel' is ignored: every output that is not a fallback receives all data")
    return output_code, fallback_ref


def _output_key(code: str, out_data: dict[str, Any]) -> str:
    """How a fallback refers to an output: its name, or its plugin when it has none."""
    name = out_data.get("name")
    if name:
        return str(name).lower()
    return code


def _resolve(ref: str, outputs: dict[str, _Output]) -> str:
    """Key of the output a fallback names: by name, or by plugin when only one output uses that plugin."""
    if ref in outputs:
        return ref
    matches: list[str] = []
    for key, out in outputs.items():
        if out.code == ref:
            matches.append(key)
    if not matches:
        raise AdapterBuildError(f"Can't find fallback output: {ref}")
    if len(matches) > 1:
        raise AdapterBuildError(f"Fallback '{ref}' matches several outputs, use one of their names: {matches}")
    return matches[0]


def _default_fallback(key: str, error_holder: ErrorHolder) -> FILE:
    leaf_tmp_dir = os.path.join(tempfile.gettempdir(), "leaf")
    os.makedirs(leaf_tmp_dir, exist_ok=True)
    # A name can hold spaces or slashes; the file name must not
    safe_key = re.sub(r"[^\w.-]", "_", key)
    tmp_path = os.path.join(leaf_tmp_dir, f"{safe_key}_fallback.json")
    logger.warning(f"No fallback configured for '{key}', defaulting to {tmp_path}")
    return FILE(filename=tmp_path, error_holder=error_holder)


def build_output_module(config: dict[str, Any], error_holder: ErrorHolder) -> OutputModule | None:
    """Builds every output in OUTPUTS; each one that is not another's fallback receives all data."""
    outputs: dict[str, _Output] = {}
    for out_data in config["OUTPUTS"]:
        code, fallback_ref = _pop_output_codes(out_data)
        key = _output_key(code, out_data)
        if key in outputs:
            raise AdapterBuildError(f"Two outputs are called '{key}': give each a different name")
        try:
            output = get_output_adapter(code)(fallback=None, error_holder=error_holder, **out_data)
        except TypeError as ex:
            raise AdapterBuildError(f"Code '{code}' missing parameters ({ex.args})")
        outputs[key] = _Output(code, fallback_ref, output)

    fallback_keys: set[str] = set()
    for out in outputs.values():
        if out.fallback:
            fallback_keys.add(_resolve(out.fallback, outputs))

    receivers: list[OutputModule] = []
    for key, out in outputs.items():
        if out.fallback:
            out.output.set_fallback(outputs[_resolve(out.fallback, outputs)].output)
        elif key not in fallback_keys:
            out.output.set_fallback(_default_fallback(key, error_holder))
        if key not in fallback_keys:
            receivers.append(out.output)

    if not receivers:
        return None
    if len(receivers) == 1:
        return receivers[0]
    return OutputGroup(receivers)


def process_instance(instance: dict[str, Any], output: OutputModule) -> EquipmentAdapter:
    """Initializes and validates an equipment adapter from config data."""
    equipment_code = instance.pop("adapter")
    instance_data = instance.pop("data")
    for alias in ("institute", "organization"):
        if alias in instance_data:
            instance_data["organisation"] = instance_data.pop(alias)
    # Keep backward-compatible alias so older leaf_register versions (which require
    # 'institute') still pass metadata validation alongside the new 'organisation' key.
    if "organisation" in instance_data and "institute" not in instance_data:
        instance_data["institute"] = instance_data["organisation"]
    # See if requirements can become optional
    requirements = None
    if "requirements" in instance:
        requirements = instance.pop("requirements")

    if "external_input" in instance:
        ei_data = instance.pop("external_input")
        ei_code = ei_data.pop("plugin")
        external_input_cls = get_external_input(ei_code)
        external_watcher = external_input_cls(**ei_data)
    else:
        external_watcher = None

    control = instance.pop("control", False)
    control_limits = cast(object, instance.pop("control_limits", None))

    adapter_cls = get_equipment_adapter(equipment_code)

    try:
        instance_id = instance_data["instance_id"]
    except KeyError:
        raise AdapterBuildError("Missing instance ID.")

    if instance_id in get_existing_ids(output):
        logger.warning(f"ID '{instance_id}' is already registered. Adapter may overwrite existing state.")

    adapter_params = inspect.signature(adapter_cls).parameters
    adapter_param_names = set(adapter_params.keys())
    fixed_params = {"instance_data", "output", "error_holder"}

    required_params = {
        name
        for name, param in adapter_params.items()
        if name not in fixed_params and param.default == inspect.Parameter.empty
    }

    if requirements is not None:
        provided_keys = set(requirements.keys())
        missing_keys = required_params - provided_keys
        unexpected_keys = provided_keys - adapter_param_names

        if missing_keys:
            raise AdapterBuildError(f"Missing required keys for '{equipment_code}': {missing_keys}")
        if unexpected_keys:
            logger.warning(f"Unexpected keys provided for '{equipment_code}': {unexpected_keys}")
    else:
        logger.info("Required parameters are: %s", required_params)
        if required_params != set():
            raise AdapterBuildError(f"Missing required keys for '{equipment_code}': {required_params}")
        logger.warning(f"No requirements provided for '{equipment_code}'.")
        requirements = {}

    try:
        error_holder = ErrorHolder(instance_id)
        logger.debug(f"Initializing {instance_id} with {adapter_cls}")
        logger.debug(f"Parameters: {instance_data}, {output}, {error_holder}")
        logger.debug(f"Requirements: {requirements}")
        logger.debug(f"Additional arguments: {instance}")
        adapter = adapter_cls(
            instance_data,
            output,
            error_holder=error_holder,
            external_watcher=external_watcher,
            **requirements,
            **instance,
        )
    except ValueError as ex:
        raise AdapterBuildError(f"Error initializing {instance_id}: {ex}")

    _attach_controller(adapter, adapter_cls, output, control, control_limits)
    return adapter


def _attach_controller(
    adapter: EquipmentAdapter,
    adapter_cls: type[EquipmentAdapter],
    output: OutputModule,
    control: bool,
    control_limits: object = None,
) -> None:
    """With control enabled, attach the AbstractController from the controller.py next to the adapter's module."""
    if not control:
        if control_limits is not None:
            raise AdapterBuildError("'control_limits' needs 'control: true'.")
        return
    if not isinstance(output, MQTT):
        raise AdapterBuildError("'control' requires an MQTT output.")
    # Locally loaded adapters are not in sys.modules, so take the path from __init__'s code object.
    controller_fp = os.path.join(os.path.dirname(inspect.getfile(adapter_cls.__init__)), "controller.py")
    if not os.path.isfile(controller_fp):
        raise AdapterBuildError(f"'control' is enabled but {controller_fp} does not exist.")
    controller_cls = load_class_from_file(controller_fp, base_class=AbstractController)
    if control_limits is not None and not isinstance(control_limits, dict):
        raise AdapterBuildError("'control_limits' must map control names to min/max.")
    try:
        controls = apply_limits(
            read_controls(os.path.dirname(controller_fp)), cast(dict[str, object], control_limits or {})
        )
    except ValueError as e:
        raise AdapterBuildError(str(e))
    adapter.set_controller(controller_cls(), controls)


def start_all_adapters_in_threads(adapters: list[EquipmentAdapter]) -> list[threading.Thread]:
    """Starts each adapter in a separate daemon thread."""
    threads: list[threading.Thread] = []
    for adapter in adapters:
        logger.info(f"Starting adapter: {adapter}")
        thread = threading.Thread(target=adapter.start, name=f"AdapterThread-{adapter}", daemon=True)
        thread.start()
        threads.append(thread)
    return threads


def run_simulation_in_thread(adapter: EquipmentAdapter, **kwargs: Any) -> threading.Thread:
    """Runs the adapter's simulate function in a separate daemon thread."""
    logger.info(f"Running simulation: {adapter}")

    def simulation() -> None:
        try:
            logger.info(f"Starting simulation with data: {kwargs}")
            adapter.simulate(**kwargs)
            logger.info("Simulation completed successfully.")
        except Exception as e:
            logger.error(f"Simulation failed: {e}", exc_info=True)

    thread = threading.Thread(target=simulation, name=f"SimThread-{adapter}", daemon=True)
    thread.start()
    return thread
