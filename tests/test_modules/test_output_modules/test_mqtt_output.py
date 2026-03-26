import os
import sys
import time
import unittest

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.output_modules.mqtt import MQTT, logger
from leaf.register.metadata import MetadataManager
from tests.mock_mqtt_client import MockBioreactorClient

# Current location of this script
curr_dir: str = os.path.dirname(os.path.realpath(__file__))


class TestMQTT(unittest.TestCase):
    def setUp(self):
        with open(curr_dir + "/../../test_config.yaml") as file:
            config = yaml.safe_load(file)

        broker = config["OUTPUTS"][0]["broker"]
        port = int(config["OUTPUTS"][0]["port"])
        try:
            un = config["OUTPUTS"][0]["username"]
            pw = config["OUTPUTS"][0]["password"]
        except KeyError:
            un = None
            pw = None

        # Cant get a connetion with the default clientid.
        self._adapter = MQTT(broker, port, username=un, password=pw, clientid=None)
        self._mock_client = MockBioreactorClient(broker, port, username=un, password=pw)

    def tearDown(self):
        pass

    def test_transmit(self):
        metadata_manager = MetadataManager()
        metadata_manager.add_equipment_value("adapter_id", "test_transmit")
        metadata_manager.add_instance_value("organisation", "test_transmit")
        metadata_manager.add_instance_value("department", "test_transmit")
        metadata_manager.add_instance_value("instance_id", "test_transmit")

        self._mock_client.subscribe(metadata_manager.experiment.start())
        time.sleep(2)
        self._adapter.transmit(metadata_manager.experiment.start(), {"tst": "tst"})
        time.sleep(2)
        for k, v in self._mock_client.messages.items():
            logger.debug(f"Received message: {k} , {v}")
            if metadata_manager.experiment.start() == k:
                break
        else:
            self.fail()

    def test_false_null_payload(self):
        test_topic = "test_false_null_payload"
        self._mock_client.subscribe(test_topic)
        time.sleep(0.5)
        test_payload = ""
        self._adapter.transmit(test_topic, test_payload)
        time.sleep(0.5)

        self.assertIn(test_topic, self._mock_client.messages)
        self.assertEqual(self._mock_client.messages[test_topic], [{}])

    def test_heartbeat(self):
        interval = 2.0
        heartbeat_topic = "leaf/test_org/test_dept/test_adapter/test_instance/heartbeat"
        adapter = MQTT(
            self._adapter._broker,
            self._adapter._port,
            heartbeat_topic=heartbeat_topic,
            heartbeat_interval=interval,
        )
        self._mock_client.subscribe(heartbeat_topic)
        time.sleep(interval + 1)
        adapter.disconnect()

        self.assertIn(heartbeat_topic, self._mock_client.messages)
        msgs = self._mock_client.messages[heartbeat_topic]
        self.assertGreaterEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["status"], "alive")
        self.assertIn("timestamp", msgs[0])


if __name__ == "__main__":
    unittest.main()
