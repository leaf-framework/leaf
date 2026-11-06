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
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.sql import SQL
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


class TestFallbacks(unittest.TestCase):
    def tearDown(self) -> None:
        try:
            self._module.disconnect()
        except Exception:
            pass
        try:
            self._mock_client.disconnect()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def setUp(self) -> None:
        mock_topic = "test_fallback/"

        # Create a unique temporary directory for each test to ensure isolation
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_store_path = os.path.join(self.temp_dir.name, "local.json")

        self._file = FILE(self.file_store_path)
        self._sql = SQL(os.path.join(self.temp_dir.name, "fallback.db"), fallback=self._file)
        self._module = MQTT(broker, port, username=un, password=pw, clientid=None, fallback=self._sql)
        self._mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)

    def _pop_with_wait(self, topic: str, timeout: float = 5.0, interval: float = 0.1):
        """Poll sql.pop() until it returns data or `timeout` elapses.

        The MQTT-disconnect -> fallback-to-sql publish this is waiting on
        happens asynchronously; a single pop() right after a fixed sleep()
        was flaky under CPU contention (e.g. running the suite without
        --forked) because the publish sometimes hadn't landed yet, making
        pop() return None and the caller's list(None) raise TypeError
        instead of a clear assertion failure.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            res = self._sql.pop(topic)
            if res is not None:
                return res
            time.sleep(interval)
        self.fail(f"sql.pop({topic!r}) still returned None after {timeout}s")

    def test_fallback_sql(self) -> None:
        mock_topic = f"test_fallback/{uuid4()}"
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)

        mock_data = {"test_fallback": "test_fallback"}
        self._module.client.loop_stop()
        self._module.client.on_disconnect = None
        self._module.client.loop_start()
        self._module.client.disconnect()
        time.sleep(1)
        self._module.transmit(mock_topic, mock_data)
        self.assertNotIn(mock_topic, self._mock_client.messages)
        res = list(self._pop_with_wait(mock_topic))
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
        self._module.set_fallback(self._file)
        time.sleep(1)
        self._module.transmit(mock_topic, mock_data)
        time.sleep(1)
        self.assertNotIn(mock_topic, self._mock_client.messages)
        self.assertIsNone(self._sql.pop(mock_topic))

        res = [
            json.loads(n) if not isinstance(n, dict) else n
            for n in self._file.retrieve(mock_topic)
            if isinstance(n, dict) or is_valid_json(n)
        ]
        self.assertIn(mock_data, res)

    def test_heartbeat_not_written_to_fallback(self) -> None:
        """A heartbeat is only meaningful live.

        With the broker unreachable it must be dropped rather than buffered in
        the fallback chain, where it would later be replayed as a stale "alive"
        (and, with no fallback at all, would trip the global
        "all outputs failed" backoff).  Ordinary data on a sibling topic still
        has to reach the fallback, so both are asserted here.
        """
        heartbeat_topic = f"test_fallback/{uuid4()}/heartbeat"
        data_topic = f"test_fallback/{uuid4()}"
        mock_data = {"test_fallback": "test_fallback"}

        self._module.client.loop_stop()
        self._module.client.on_disconnect = None
        self._module.client.loop_start()
        self._module.client.disconnect()
        self._module.set_fallback(self._file)
        time.sleep(1)

        self._module._heartbeat_topics = {heartbeat_topic}
        self._module._heartbeat_interval = 0.5
        self._module._start_heartbeat()
        time.sleep(2)
        self._module._stop_heartbeat()

        # Ordinary data on the same (broken) connection does land in the fallback.
        self._module.transmit(data_topic, mock_data)
        time.sleep(1)

        self.assertIsNone(self._sql.pop(heartbeat_topic))
        self.assertIsNone(self._file.retrieve(heartbeat_topic))
        self.assertIsNotNone(self._file.retrieve(data_topic))

    def test_pop_all_messages(self):
        mock_topic = f"test_fallback/{uuid4()}"
        self._mock_client.subscribe(mock_topic)
        time.sleep(2)
        organisation = "test_pop_all_messages_organisation"
        department = "test_pop_all_messages_department"
        adapter_id = "test_pop_all_messages_adapter_id"
        instance_id = "test_pop_all_messages_instance_id"
        experiment_id = "test_pop_all_messages_experiment_id"
        measurement_id = "test_pop_all_messages_measurement_id"

        manager = MetadataManager()
        manager.add_equipment_value("adapter_id", adapter_id)
        manager.add_instance_value("organisation", organisation)
        manager.add_instance_value("department", department)
        manager.add_instance_value("instance_id", instance_id)

        inp_messages = {
            manager.measurement(experiment_id=experiment_id, measurement=measurement_id): [
                '{"A":"A"}',
                '{"B":"B"}',
                '{"C":"C"}',
            ],
            manager.start(): ['{"D":"D"}', '{"E":"E"}', '{"F":"F"}'],
        }
        for topic, messages in inp_messages.items():
            for message in messages:
                self._sql.transmit(topic, json.loads(message))
                time.sleep(0.1)

        messages = list(self._module.pop_all_messages())
        self.assertTrue(len(messages) > 0)
        for topic, message in messages:
            inp_messages[topic] = [json.loads(item) if isinstance(item, str) else item for item in inp_messages[topic]]
            self.assertIn(topic, inp_messages)
            self.assertIn(message, inp_messages[topic])
        self.assertIsNone(self._sql.pop())

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

        organisation = "test_pop_all_messages_organisation"
        department = "test_pop_all_messages_department"
        adapter_id = "test_pop_all_messages_adapter_id"
        instance_id = "test_pop_all_messages_instance_id"
        experiment_id = "test_pop_all_messages_experiment_id"
        measurement_id = "test_pop_all_messages_measurement_id"

        manager = MetadataManager()
        manager.add_equipment_value("adapter_id", adapter_id)
        manager.add_instance_value("organisation", organisation)
        manager.add_instance_value("department", department)
        manager.add_instance_value("instance_id", instance_id)

        sql_messages = {
            manager.measurement(experiment_id=experiment_id, measurement=measurement_id): [
                '{"A":"A"}',
                '{"B":"B"}',
                '{"C":"C"}',
            ],
            manager.start(): ['{"D":"D"}', '{"E":"E"}', '{"F":"F"}'],
        }
        file_messages = {
            manager.measurement(experiment_id=experiment_id, measurement=measurement_id): [
                '{"G":"G"}',
                '{"H":"H"}',
                '{"I":"I"}',
            ],
            manager.start(): ['{"J":"J"}', '{"K":"K"}', '{"L":"L"}'],
        }
        for topic, messages in sql_messages.items():
            for message in messages:
                self._sql.transmit(topic, json.loads(message))
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
            self.assertTrue(topic in sql_messages or topic in file_messages)

            # FILE module returns message as a list, SQL returns the dict
            if isinstance(message, list):
                # FILE module - message is wrapped in a list
                for item in message:
                    # Parse if string, use as-is if dict
                    parsed_item = json.loads(item) if isinstance(item, str) else item
                    item_str = json.dumps(parsed_item, separators=(",", ":"))

                    # Check if this message is in either sql or file expected messages
                    found = False
                    if topic in file_messages and item_str in file_messages[topic]:
                        found = True
                    if topic in sql_messages and item_str in sql_messages[topic]:
                        found = True
                    self.assertTrue(found, f"Message {item_str} not found in expected messages for topic {topic}")
            else:
                # SQL module returns the dict - convert to JSON string for comparison
                message_str = json.dumps(message, separators=(",", ":")) if isinstance(message, dict) else message
                found = False
                if topic in sql_messages and message_str in sql_messages[topic]:
                    found = True
                if topic in file_messages and message_str in file_messages[topic]:
                    found = True
                self.assertTrue(found, f"Message {message_str} not found in expected messages for topic {topic}")

        self.assertIsNone(self._file.pop())
        self.assertIsNone(self._sql.pop())


def is_valid_json(item):
    try:
        json.loads(item)
        return True
    except json.JSONDecodeError:
        return False


if __name__ == "__main__":
    unittest.main()
