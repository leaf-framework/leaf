import logging
import os
import time
import uuid
from threading import Thread
from unittest import mock

import paho.mqtt.client as mqtt
import pytest
import yaml
from paho.mqtt.enums import CallbackAPIVersion

from leaf.adapters.equipment_adapter import AbstractController, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.output_modules.mqtt import MQTT
from leaf.register.metadata import MetadataManager
from leaf.registry.loader import load_class_from_file
from leaf.registry.registry import register
from leaf.utility.running_utilities import process_instance

with open(os.path.join(os.path.dirname(__file__), "..", "test_config.yaml")) as f:
    _mqtt_cfg = yaml.safe_load(f)["OUTPUTS"][0]
broker = _mqtt_cfg["broker"]
port = int(_mqtt_cfg["port"])


def _msg(topic: str, payload: str) -> mqtt.MQTTMessage:
    msg = mqtt.MQTTMessage(topic=topic.encode())
    msg.payload = payload.encode()
    return msg


def test_mqtt_subscribe_routes_to_callback():
    with mock.patch.object(MQTT, "connect"):
        output = MQTT("localhost", heartbeat_interval=0)
    output.client = mock.MagicMock()
    received = []
    output.subscribe("a/control", lambda t, d: received.append((t, d)))
    output.on_message(output.client, None, _msg("a/control", "start"))
    output.on_message(output.client, None, _msg("a/other", "ignored"))
    output.unsubscribe("a/control")
    output.on_message(output.client, None, _msg("a/control", "after"))
    assert received == [("a/control", "start")]


def test_control_topic_and_failing_controller():
    mm = MetadataManager()
    mm.add_instance_data({"instance_id": "i1", "organisation": "o", "department": "d"})
    assert mm.control().endswith("/i1/control")

    class Broken(AbstractController):
        def control(self, topic, data):
            raise RuntimeError("boom")

    holder = ErrorHolder("i1")
    adapter = mock.MagicMock(_logger=logging.getLogger(), _error_holder=holder)
    adapter._handle_exception = lambda e: EquipmentAdapter._handle_exception(adapter, e)
    EquipmentAdapter.set_controller(adapter, Broken())
    EquipmentAdapter._on_control(adapter, "t", "go")
    assert len(holder.get_unseen_errors()) == 1


ADAPTER_PY = """
from leaf.adapters.core_adapters.discrete_experiment_adapter import DiscreteExperimentAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.register.metadata import MetadataManager


class Interpreter(AbstractInterpreter):
    def measurement(self, data):
        return data


class Adapter(DiscreteExperimentAdapter):
    def __init__(self, instance_data, output, watch_dir, error_holder=None, external_watcher=None):
        metadata_manager = MetadataManager()
        watcher = FileWatcher(watch_dir, metadata_manager, filenames="none.csv")
        super().__init__(instance_data, watcher, output, Interpreter(),
                         error_holder=error_holder, metadata_manager=metadata_manager)
        self._metadata_manager.add_equipment_data({"adapter_id": "ControlTest"})
        self.received = []
"""

CONTROLLER_PY = """
from leaf.adapters.equipment_adapter import AbstractController


class Controller(AbstractController):
    def control(self, topic, data):
        self.adapter.received.append(data)
"""


def _wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_control_end_to_end(tmp_path):
    (tmp_path / "adapter.py").write_text(ADAPTER_PY)
    (tmp_path / "controller.py").write_text(CONTROLLER_PY)
    register("equipment", "ControlTest", load_class_from_file(str(tmp_path / "adapter.py")))

    output = MQTT(broker, port, heartbeat_interval=0)
    instance_id = f"control-{uuid.uuid4()}"
    adapter = process_instance(
        {
            "adapter": "ControlTest",
            "control": True,
            "data": {"instance_id": instance_id, "organisation": "test", "department": "test"},
            "requirements": {"watch_dir": str(tmp_path)},
        },
        output,
    )
    thread = Thread(target=adapter.start, daemon=True)
    thread.start()

    sender = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    sender.connect(broker, port)
    sender.loop_start()
    try:
        topic = adapter._metadata_manager.control()
        assert _wait_for(lambda: topic in output._subscriptions)
        time.sleep(1)
        sender.publish(topic, "start").wait_for_publish()
        assert _wait_for(lambda: vars(adapter)["received"] == ["start"])

        # Clean session: the control topic must be resubscribed after a reconnect.
        output.disconnect()
        output.connect()
        assert _wait_for(output.is_connected)
        time.sleep(1)
        sender.publish(topic, "stop").wait_for_publish()
        assert _wait_for(lambda: vars(adapter)["received"] == ["start", "stop"])
    finally:
        sender.loop_stop()
        sender.disconnect()
        adapter.stop()
        output.disconnect()
    assert topic not in output._subscriptions


def test_control_without_controller_file(tmp_path):
    (tmp_path / "adapter.py").write_text(ADAPTER_PY)
    register("equipment", "ControlTest", load_class_from_file(str(tmp_path / "adapter.py")))
    with mock.patch.object(MQTT, "connect"):
        output = MQTT(broker, port, heartbeat_interval=0)
    with pytest.raises(AdapterBuildError, match="controller.py"):
        process_instance(
            {
                "adapter": "ControlTest",
                "control": True,
                "data": {"instance_id": "x", "organisation": "test", "department": "test"},
                "requirements": {"watch_dir": str(tmp_path)},
            },
            output,
        )
