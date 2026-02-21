import json
import os
import sys
import tempfile
import time
import unittest
from uuid import uuid4

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.output_modules.file import FILE
from leaf.modules.output_modules.keydb import KEYDB
from leaf.modules.output_modules.mqtt import MQTT
from leaf.register.metadata import MetadataManager
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir = os.path.dirname(os.path.realpath(__file__))
config_path = os.path.join(curr_dir, "..", "..", "test_config.yaml")

with open(config_path) as file:
    config = yaml.safe_load(file)

broker = config["OUTPUTS"][0]["broker"]
port = int(config["OUTPUTS"][0]["port"])
try:
    un = config["OUTPUTS"][0]["username"]
    pw = config["OUTPUTS"][0]["password"]
except KeyError:
    un = None
    pw = None

db_host = "localhost"


class TestFallbacks(unittest.TestCase):
    def setUp(self) -> None:
        mock_topic = "test_fallback/"

        # Create a unique temporary directory for each test to ensure isolation
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_store_path = os.path.join(self.temp_dir.name, "local.json")

        self._file = FILE(self.file_store_path)
        self._keydb: KEYDB = KEYDB(db_host, fallback=self._file, db=2)
        self._keydb.connect()
        self._module = MQTT(broker, port, username=un, password=pw, clientid=None, fallback=self._keydb)
        self._mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)

    def test_fallback_keydb(self) -> None:
        mock_topic = f"test_fallback/{uuid4()}"
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)

        res = self._keydb.pop(mock_topic)
        mock_data = {"test_fallback": "test_fallback"}
        self._module.client.loop_stop()
        self._module.client.on_disconnect = None
        self._module.client.loop_start()
        self._module.client.disconnect()
        time.sleep(1)
        self._module.transmit(mock_topic, mock_data)
        time.sleep(1)
        self.assertNotIn(mock_topic, self._mock_client.messages)
        res = list(self._keydb.pop(mock_topic))
        self.assertEqual(mock_topic, res[0])
        self.assertEqual(mock_data, res[1])

    def test_fallback_file(self) -> None:
        mock_topic = f"test_fallback/{uuid4()}"
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)
        mock_data = {"test_fallback": "test_fallback"}
        self._module.client.loop_stop()
        self._module.client.on_disconnect = None
        self._module.client.loop_start()
        self._module.client.disconnect()
        self._keydb.disconnect()
        time.sleep(1)
        self._module.transmit(mock_topic, mock_data)
        time.sleep(1)
        self.assertNotIn(mock_topic, self._mock_client.messages)
        res = self._keydb.pop(mock_topic)
        self.assertEqual(res, None)

        res = [
            json.loads(n) if not isinstance(n, dict) else n
            for n in self._file.retrieve(mock_topic)
            if isinstance(n, dict) or is_valid_json(n)
        ]
        self.assertIn(mock_data, res)

    def test_pop_all_messages(self):
        mock_topic = f"test_fallback/{uuid4()}"
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)
        self._keydb.connect()
        institute = "test_pop_all_messages_institute"
        department =  "test_pop_all_messages_department"
        adapter_id = "test_pop_all_messages_adapter_id"
        instance_id = "test_pop_all_messages_instance_id"
        experiment_id = "test_pop_all_messages_experiment_id"
        measurement_id = "test_pop_all_messages_measurement_id"

        manager = MetadataManager()
        manager.add_equipment_value("adapter_id", adapter_id)
        manager.add_instance_value("institute", institute)
        manager.add_instance_value("department", department)
        manager.add_instance_value("instance_id", instance_id)

        inp_messages = {
            manager.experiment.measurement(experiment_id=experiment_id, measurement=measurement_id): [
                '{"A":"A"}',
                '{"B":"B"}',
                '{"C":"C"}',
            ],
            manager.experiment.start(): ['{"D":"D"}', '{"E":"E"}', '{"F":"F"}'],
        }
        for topic, messages in inp_messages.items():
            for message in messages:
                self._keydb.transmit(topic, message)
                time.sleep(0.1)

        messages = list(self._module.pop_all_messages())
        self.assertTrue(len(messages) > 0)
        for topic, message in messages:
            inp_messages[topic] = [json.loads(item) if isinstance(item, str) else item for item in inp_messages[topic]]
            self.assertIn(topic, inp_messages)
            self.assertIn(message, inp_messages[topic])
        self.assertIsNone(self._keydb.pop())

        for topic, messages in inp_messages.items():
            for message in messages:
                self._file.transmit(topic, message)
                time.sleep(1)

        messages = list(self._module.pop_all_messages())
        self.assertTrue(len(messages) > 0)
        for topic, message in messages:
            # Reduce issues with parallel tests
            if topic not in inp_messages:
                continue
            self.assertIn(topic, inp_messages)
            # FILE module returns message as a list, so check each item
            if isinstance(message, list):
                for item in message:
                    self.assertIn(item, inp_messages[topic])
            else:
                self.assertIn(message, inp_messages[topic])
        self.assertIsNone(self._file.pop())

    def test_pop_all_messages_multi_output(self):
        mock_topic = f"test_fallback/{uuid4()}"
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)

        self._keydb.connect()
        institute = "test_pop_all_messages_institute"
        department = "test_pop_all_messages_department"
        adapter_id = "test_pop_all_messages_adapter_id"
        instance_id = "test_pop_all_messages_instance_id"
        experiment_id = "test_pop_all_messages_experiment_id"
        measurement_id = "test_pop_all_messages_measurement_id"

        manager = MetadataManager()
        manager.add_equipment_value("adapter_id", adapter_id)
        manager.add_instance_value("institute", institute)
        manager.add_instance_value("department", department)
        manager.add_instance_value("instance_id", instance_id)

        keydb_messages = {
            manager.experiment.measurement(experiment_id=experiment_id, measurement=measurement_id): [
                '{"A":"A"}',
                '{"B":"B"}',
                '{"C":"C"}',
            ],
            manager.experiment.start(): ['{"D":"D"}', '{"E":"E"}', '{"F":"F"}'],
        }
        file_messages = {
            manager.experiment.measurement(experiment_id=experiment_id, measurement=measurement_id): [
                '{"G":"G"}',
                '{"H":"H"}',
                '{"I":"I"}',
            ],
            manager.experiment.start(): ['{"J":"J"}', '{"K":"K"}', '{"L":"L"}'],
        }
        for topic, messages in keydb_messages.items():
            for message in messages:
                self._keydb.transmit(topic, message)
                time.sleep(0.1)
        for topic, messages in file_messages.items():
            for message in messages:
                self._file.transmit(topic, message)
                time.sleep(0.1)

        messages = list(self._module.pop_all_messages())
        # Verify we got messages from both modules
        self.assertTrue(len(messages) > 0)

        for topic, message in messages:
            # Check topic is valid
            self.assertTrue(topic in keydb_messages or topic in file_messages)

            # FILE module returns message as a list, KEYDB returns as dict/string
            if isinstance(message, list):
                # FILE module - message is wrapped in a list
                for item in message:
                    # Parse if string, use as-is if dict
                    parsed_item = json.loads(item) if isinstance(item, str) else item
                    item_str = json.dumps(parsed_item, separators=(",", ":"))

                    # Check if this message is in either keydb or file expected messages
                    found = False
                    if topic in file_messages and item_str in file_messages[topic]:
                        found = True
                    if topic in keydb_messages and item_str in keydb_messages[topic]:
                        found = True
                    self.assertTrue(found, f"Message {item_str} not found in expected messages for topic {topic}")
            else:
                # KEYDB module returns dict directly - convert to JSON string for comparison
                message_str = json.dumps(message, separators=(",", ":")) if isinstance(message, dict) else message
                found = False
                if topic in keydb_messages and message_str in keydb_messages[topic]:
                    found = True
                if topic in file_messages and message_str in file_messages[topic]:
                    found = True
                self.assertTrue(found, f"Message {message_str} not found in expected messages for topic {topic}")

        self.assertIsNone(self._file.pop())
        self.assertIsNone(self._keydb.pop())


def is_valid_json(item):
    try:
        json.loads(item)
        return True
    except json.JSONDecodeError:
        return False


if __name__ == "__main__":
    unittest.main()
