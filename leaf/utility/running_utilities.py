import threading
import time
import logging
import inspect
from typing import Any, Optional

from leaf.utility.logger.logger_utils import get_logger
from leaf_register.topic_utilities import topic_utilities
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.output_module import OutputModule
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.error_handler.error_holder import ErrorHolder
from leaf.adapters.equipment_adapter import EquipmentAdapter
from leaf.registry.registry import (
    get_equipment_adapter,
    get_output_adapter,
    get_external_input
)

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
        thread = threading.Thread(target=output_messages,
                                  args=(output,), daemon=True)
        thread.start()


def output_messages(output_module: OutputModule) -> None:
    """Transmits all buffered messages after reconnecting output module."""
    for topic, message in output_module.pop_all_messages():
        output_module.transmit(topic, message)


def get_existing_ids(output_module: OutputModule,
                     time_to_sleep: float = 5.0) -> list[str]:
    """Returns instance IDs of equipment already present in the system."""
    if not isinstance(output_module, MQTT):
        return []
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


def build_output_module(config: dict[str, Any],
                        error_holder: ErrorHolder) -> Optional[OutputModule]:
    """Finds, initializes, and connects all output adapters defined in config."""
    outputs = config["OUTPUTS"]
    output_objects = {}
    fallback_codes = set()

    for out_data in outputs:
        output_code = out_data.pop("plugin")
        fallback_code = out_data.pop("fallback", None)
        if fallback_code:
            fallback_codes.add(fallback_code)
        output_objects[output_code] = {
            "data": out_data,
            "fallback_code": fallback_code,
            "output": None
        }

    for code, out_data in output_objects.items():
        try:
            adapter_cls = get_output_adapter(code)
            output_objects[code]["output"] = adapter_cls(
                fallback=None, error_holder=error_holder,
                **out_data["data"]
            )
        except TypeError as ex:
            raise AdapterBuildError(f"Code '{code}' missing parameters ({ex.args})")

    for code, out_data in output_objects.items():
        if out_data["fallback_code"]:
            fallback_code = out_data["fallback_code"]
            if fallback_code not in output_objects:
                raise AdapterBuildError(f"Can't find output: {fallback_code}")
            output_objects[code]["output"].set_fallback(output_objects[fallback_code]["output"])

    for code in sorted(output_objects):
        if code not in fallback_codes:
            return output_objects[code]["output"]

    return None


def process_instance(instance: dict[str, Any],
                     output: OutputModule) -> EquipmentAdapter:
    """Initializes and validates an equipment adapter from config data."""
    equipment_code = instance.pop("adapter")
    instance_data = instance.pop("data")
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
        name for name, param in adapter_params.items()
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
        return adapter_cls(
            instance_data,
            output,
            error_holder=error_holder,
            external_watcher=external_watcher,
            **requirements,
            **instance
        )
    except ValueError as ex:
        raise AdapterBuildError(f"Error initializing {instance_id}: {ex}")


def start_all_adapters_in_threads(adapters: list[EquipmentAdapter]) -> list[threading.Thread]:
    """Starts each adapter in a separate daemon thread."""
    threads: list[threading.Thread] = []
    for adapter in adapters:
        logger.info(f"Starting adapter: {adapter}")
        thread = threading.Thread(target=adapter.start,
                                  name=f"AdapterThread-{adapter}",
                                  daemon=True)
        thread.start()
        threads.append(thread)
    return threads


def run_simulation_in_thread(adapter: EquipmentAdapter,
                             **kwargs: Any) -> threading.Thread:
    """Runs the adapter's simulate function in a separate daemon thread."""
    logger.info(f"Running simulation: {adapter}")

    def simulation() -> None:
        try:
            logger.info(f"Starting simulation with data: {kwargs}")
            adapter.simulate(**kwargs)
            logger.info("Simulation completed successfully.")
        except Exception as e:
            logger.error(f"Simulation failed: {e}", exc_info=True)

    thread = threading.Thread(target=simulation,
                              name=f"SimThread-{adapter}",
                              daemon=True)
    thread.start()
    return thread
