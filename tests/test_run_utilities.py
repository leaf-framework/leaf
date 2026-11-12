import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.output_modules.file import FILE
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.output_modules.sql import SQL
from leaf.register.metadata import MetadataManager
from leaf.registry.registry import discover_from_config
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.output_group import OutputGroup
from leaf.utility.running_utilities import build_output_module, handle_disabled_modules
from tests.mock_mqtt_client import MockBioreactorClient

logger = get_logger(__name__, log_file="test_run_utilities.log", error_log_file="test_run_utilities_error.log")

curr_dir: str = os.path.dirname(os.path.realpath(__file__))

with open(os.path.join(curr_dir, "test_config.yaml")) as file:
    config = yaml.safe_load(file)

broker = config["OUTPUTS"][0]["broker"]
port = int(config["OUTPUTS"][0]["port"])
try:
    un = config["OUTPUTS"][0]["username"]
    pw = config["OUTPUTS"][0]["password"]
except KeyError:
    un = None
    pw = None

curr_dir = os.path.dirname(os.path.realpath(__file__))
mock_functional_adapter_path = os.path.join(curr_dir, "mock_functional_adapter")


class TestRunUtilities(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_store_path = os.path.join(self.temp_dir.name, "local.json")

        self._file = FILE(self.file_store_path)
        self._sql = SQL(os.path.join(self.temp_dir.name, "fallback.db"), fallback=self._file)
        self._module = MQTT(broker, port, username=un, password=pw, clientid=None, fallback=self._sql)
        self._mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        time.sleep(2)

    def test_handle_disabled_modules(self):
        timeout = 2
        organisation = "test_pop_all_messages_organisation"
        adapter_id = "test_pop_all_messages_adapter_id"
        instance_id = "test_pop_all_messages_instance_id"
        experiment_id = "test_pop_all_messages_experiment_id"
        measurement_id = "test_pop_all_messages_measurement_id"

        manager = MetadataManager()
        manager.add_equipment_value("adapter_id", adapter_id)
        manager.add_instance_value("organisation", organisation)
        manager.add_instance_value("instance_id", instance_id)

        measurement_topic = manager.measurement(experiment_id=experiment_id, measurement=measurement_id)
        start_topic = manager.start()

        inp_messages = {
            measurement_topic: ['{"A":"A"}', '{"B":"B"}', '{"C":"C"}'],
            start_topic: ['{"D":"D"}', '{"E":"E"}', '{"F":"F"}'],
        }

        for topic in inp_messages:
            self._mock_client.subscribe(topic)

        for topic, messages in inp_messages.items():
            for message in messages:
                self._sql.transmit(topic, json.loads(message))
                time.sleep(0.1)
        self._module.disable()
        time.sleep(timeout * 2)
        handle_disabled_modules(self._module, timeout)
        time.sleep(1)
        for k, v in self._mock_client.messages.items():
            # Skip other topics for parallel tests
            if not k.startswith(organisation):
                continue
            self.assertIn(k, inp_messages)
            # Invert the list to match the order of messages
            v = list(reversed(v))
            w = [json.loads(item) for item in inp_messages[k]]

            print(f"Expected messages for topic {k}: {w}")
            print(f"Received messages for topic {k}: {v}")

            self.assertEqual(len(v), len(inp_messages[k]))
            self.assertEqual(v, w)
        file_pop = self._file.pop()
        self.assertIsNone(file_pop)

    """
    def test_stop_all_adapters(self):
        error_holder = ErrorHolder()
        output = MQTT(
            broker,
            port,
            username=un,
            password=pw,
            clientid=None,
            error_holder=error_holder,
        )

        # output = FILE("Tst.tmp")

        write_dir = tempfile.TemporaryDirectory()
        write_file = os.path.join(write_dir.name, "tmp1.csv")

        ins = [
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": f"{uuid.uuid4()}",
                        "organisation": f"{uuid.uuid4()}",
                    },
                    "requirements": {"write_file": write_file},
                }
            }
        ]

        def _start() -> Thread:
            mthread = Thread(
                target=run_adapters,
                args=[ins, output, error_holder],
                kwargs={"external_adapter": mock_functional_adapter_path},
            )
            mthread.start()
            return mthread

        def _stop(thread: Thread) -> None:
            stop_all_adapters()
            time.sleep(10)

        thread = _start()
        time.sleep(5)
        _stop(thread)
'
    """


if __name__ == "__main__":
    unittest.main()


def _build(tmp_path: Path, outputs: list[dict[str, Any]]) -> OutputModule | None:
    config = {"OUTPUTS": outputs}
    discover_from_config(config)
    return build_output_module(config, ErrorHolder("outputs"))


def test_every_output_receives_data(tmp_path: Path) -> None:
    # Used to keep only the alphabetically first one and silently drop the other
    output = _build(
        tmp_path,
        [
            {"plugin": "SQL", "filename": str(tmp_path / "a.db")},
            {"plugin": "FILE", "filename": str(tmp_path / "b.json")},
        ],
    )
    assert isinstance(output, OutputGroup)
    members = output.outputs()
    assert [type(member) for member in members] == [SQL, FILE]
    # Each one buffers to its own file when it fails
    assert members[0]._fallback is not members[1]._fallback


def test_same_plugin_needs_names(tmp_path: Path) -> None:
    files = [
        {"plugin": "FILE", "filename": str(tmp_path / "a.json")},
        {"plugin": "file", "filename": str(tmp_path / "b.json")},
    ]
    with pytest.raises(AdapterBuildError, match="give each a different name"):
        _ = _build(tmp_path, files)


def test_fallback_by_name_or_plugin(tmp_path: Path) -> None:
    output = _build(
        tmp_path,
        [
            {"plugin": "FILE", "name": "Local", "filename": str(tmp_path / "local.json"), "fallback": "sql"},
            {"plugin": "FILE", "name": "share", "filename": str(tmp_path / "share.json"), "fallback": "LOCAL"},
            {"plugin": "SQL", "filename": str(tmp_path / "buffer.db")},
        ],
    )
    # local is share's fallback and sql is local's, so only share receives the data directly
    assert isinstance(output, FILE)
    assert output.name == "share"
    assert output._fallback is not None
    assert output._fallback.name == "Local"
    assert isinstance(output._fallback._fallback, SQL)


def test_fallback_by_plugin_must_be_unique(tmp_path: Path) -> None:
    files = [
        {"plugin": "FILE", "name": "a", "filename": str(tmp_path / "a.json")},
        {"plugin": "FILE", "name": "b", "filename": str(tmp_path / "b.json")},
        {"plugin": "SQL", "filename": str(tmp_path / "c.db"), "fallback": "file"},
    ]
    with pytest.raises(AdapterBuildError, match="use one of their names"):
        _ = _build(tmp_path, files)


class _Down(FILE):
    def transmit(self, topic: str, data: str | dict[str, Any] | None = None) -> bool:
        return False


def test_group_sends_past_a_failing_output(tmp_path: Path) -> None:
    good = FILE(str(tmp_path / "good.json"))
    group = OutputGroup([_Down(str(tmp_path / "down.json")), good])
    assert not group.transmit("topic", {"value": 1})
    assert (tmp_path / "good.json").read_text() == '{"topic":[{"value":1}]}\n'
