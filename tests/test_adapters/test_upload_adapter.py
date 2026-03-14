import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from threading import Thread

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.adapters.core_adapters.upload_adapter import UploadAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.modules.output_modules.mqtt import MQTT
from leaf.register.metadata import MetadataManager
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir = os.path.dirname(os.path.realpath(__file__))
config_path = os.path.join(curr_dir, "..", "test_config.yaml")

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

test_file_dir = os.path.join(curr_dir, "..", "static_files")
initial_file = os.path.join(test_file_dir, "upload_test.txt")


def _upload_file(watch_dir: Path) -> None:
    watch_file = os.path.join(watch_dir, os.path.basename(initial_file))
    if os.path.isfile(watch_file):
        os.remove(watch_file)
    shutil.copyfile(initial_file, watch_file)
    time.sleep(1)


class MockUploadInterpreter(AbstractInterpreter):
    def __init__(self) -> None:
        super().__init__()
        self.id = "TestUploadAdapter"

    def metadata(self, data):
        return {"experiment_id": self.id, "metadata": data}

    def measurement(self, data):
        return {"experiment_id": self.id, "data": data}

    def simulate(self):
        return


class MockUploadAdapter(UploadAdapter):
    def __init__(self, instance_data, equipment_data, output, watch_dir):
        metadata_manager = MetadataManager()
        metadata_manager.add_instance_data(instance_data)
        interpreter = MockUploadInterpreter()
        super().__init__(equipment_data, output, interpreter, watch_dir, metadata_manager=metadata_manager)


class TestUploadAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

        unique_id = str(uuid.uuid4())
        self.watch_dir = Path(self.temp_dir.name)
        self.instance_data = {
            "root": f"ROOT_TestUploadAdapter_{unique_id}",
            "instance_id": unique_id,
            "organisation": f"TestUploadAdapter_{unique_id}_ins",
            "department": f"TestUploadAdapter_{unique_id}_dep",
        }
        self.equipment_data = {
            "adapter_id": f"TestUploadAdapter_{unique_id}_equipment",
        }

        self.mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        self.output = MQTT(broker, port, username=un, password=pw)
        self._adapter = MockUploadAdapter(self.instance_data, self.equipment_data, self.output, str(self.watch_dir))

        self.details_topic = self._adapter._metadata_manager.details()
        self.start_topic = self._adapter._metadata_manager.experiment.start()
        self.stop_topic = self._adapter._metadata_manager.experiment.stop()
        self.running_topic = self._adapter._metadata_manager.running()

        self._flush_topics()
        time.sleep(1)
        wildcard_measure = self._adapter._metadata_manager.experiment.measurement()
        self.mock_client.subscribe(self.start_topic)
        self.mock_client.subscribe(self.stop_topic)
        self.mock_client.subscribe(self.running_topic)
        self.mock_client.subscribe(self.details_topic)
        self.mock_client.subscribe(wildcard_measure)
        time.sleep(1)

    def tearDown(self) -> None:
        self._adapter.stop()
        self._flush_topics()
        self.mock_client.reset_messages()
        self.temp_dir.cleanup()

    def wait_for_adapter_start(self, adapter):
        timeout = 30
        cur_count = 0
        while not adapter.is_running():
            time.sleep(0.5)
            cur_count += 1
            if cur_count > timeout:
                self.fail("Unable to initialise.")

    def _flush_topics(self) -> None:
        self.mock_client.flush(self.details_topic)
        self.mock_client.flush(self.start_topic)
        self.mock_client.flush(self.stop_topic)
        self.mock_client.flush(self.running_topic)

    def test_details(self) -> None:
        self._flush_topics()
        self.mock_client.reset_messages()
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        self._adapter.stop()
        mthread.join()
        self.assertIn(self.details_topic, self.mock_client.messages)
        self.assertTrue(len(self.mock_client.messages[self.details_topic]) == 1)
        details_data = self.mock_client.messages[self.details_topic][0]
        for k, v in self.instance_data.items():
            self.assertIn(k, details_data["instance"])
            self.assertEqual(v, details_data["instance"][k])
        self._flush_topics()
        self.mock_client.reset_messages()

    def test_start(self) -> None:
        self._flush_topics()
        self.mock_client.reset_messages()
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        _upload_file(self.watch_dir)
        time.sleep(1)
        self._adapter.stop()
        mthread.join()
        time.sleep(1)

        self.assertIn(self.start_topic, self.mock_client.messages)
        self.assertTrue(len(self.mock_client.messages[self.start_topic]) == 1)
        self.assertIn("experiment_id", self.mock_client.messages[self.start_topic][0])
        self.assertIn(
            self._adapter._interpreter.id,
            self.mock_client.messages[self.start_topic][0]["experiment_id"],
        )
        self.assertIn(self.running_topic, self.mock_client.messages)
        expected_run = "True"
        self.assertEqual(self.mock_client.messages[self.running_topic][0], expected_run)

        self.assertIn(self.stop_topic, self.mock_client.messages)
        self._flush_topics()
        self.mock_client.reset_messages()

    def test_running(self) -> None:
        self._flush_topics()
        self.mock_client.reset_messages()

        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        _upload_file(self.watch_dir)
        time.sleep(1)
        self._adapter.stop()
        mthread.join()

        self.assertIn(self.running_topic, self.mock_client.messages)
        expected_run = "True"
        self.assertEqual(self.mock_client.messages[self.running_topic][0], expected_run)


if __name__ == "__main__":
    unittest.main()
