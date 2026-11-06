import os
import sys
import tempfile
import time
import unittest
import uuid
from threading import Thread

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.adapters.core_adapters.continuous_experiment_adapter import ContinuousExperimentAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.file_watcher import FileWatcher
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
initial_file = os.path.join(test_file_dir, "biolector1_metadata.csv")
measurement_file = os.path.join(test_file_dir, "biolector1_measurement.csv")
all_data_file = os.path.join(test_file_dir, "biolector1_full.csv")


class MockBioreactorInterpreter(AbstractInterpreter):
    def __init__(self) -> None:
        super().__init__()
        self.id = "TestBioreactor"

    def metadata(self, data):
        return data

    def measurement(self, data):
        return super().measurement(data)

    def simulate(self):
        return


class MockEquipmentAdapter(ContinuousExperimentAdapter):
    def __init__(self, instance_data, equipment_data, fp, experiment_timeout=None):
        metadata_manager = MetadataManager()
        directory = os.path.dirname(fp)
        filename = os.path.basename(fp)
        watcher = FileWatcher(directory, metadata_manager, filenames=filename)
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        error_holder = ErrorHolder()
        metadata_manager.add_instance_data(instance_data)
        super().__init__(
            equipment_data,
            watcher,
            output,
            MockBioreactorInterpreter(),
            metadata_manager=metadata_manager,
            error_holder=error_holder,
            experiment_timeout=experiment_timeout,
        )


class TestEquipmentAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def initialize_experiment(self, **kwargs):
        """
        Helper function to initialize a unique MockEquipmentAdapter
        instance with unique file paths and instance data.
        """

        unique_instance_id = str(uuid.uuid4())
        unique_organisation = "TestInstitute_"  # + unique_instance_id[:8]
        unique_department = "TestDepartment_"

        unique_file_name = f"TestBioreactor_{unique_instance_id}.txt"
        self.text_watch_file = os.path.join(self.temp_dir.name, unique_file_name)

        instance_data = {
            "instance_id": unique_instance_id,
            "organisation": unique_organisation,
            "department": unique_department,
        }
        equipment_data = {"adapter_id": "TestBioreactor_transmit_" + unique_instance_id}
        self.mock_client = MockBioreactorClient(broker, port, username=un, password=pw)

        self._adapter = MockEquipmentAdapter(instance_data, equipment_data, self.text_watch_file, **kwargs)

        self.details_topic = self._adapter._metadata_manager.details()
        self.start_topic = self._adapter._metadata_manager.start()
        self.stop_topic = self._adapter._metadata_manager.stop()

        self.mock_client.flush(self.details_topic)
        self.mock_client.flush(self.start_topic)
        self.mock_client.flush(self.stop_topic)
        time.sleep(2)
        self.mock_client.subscribe(self.start_topic)
        time.sleep(0.1)
        self.mock_client.subscribe(self.stop_topic)
        time.sleep(0.1)
        self.mock_client.subscribe(self.details_topic)
        time.sleep(2)

    def tearDown(self):
        try:
            self._adapter.stop()
        except Exception:
            pass
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass
        try:
            self.mock_client.reset_messages()
        except Exception:
            pass

    def wait_for_adapter_start(self, adapter):
        timeout = 30
        cur_count = 0
        while not adapter.is_running():
            time.sleep(0.5)
            cur_count += 1
            if cur_count > timeout:
                self.fail("Unable to initialise.")

    def test_details(self):
        self.initialize_experiment()
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        self._adapter.stop()
        mthread.join()
        time.sleep(2)
        self.assertIn(self.details_topic, self.mock_client.messages)
        self.assertEqual(len(self.mock_client.messages[self.details_topic]), 1)

    def test_running(self):
        self.initialize_experiment()
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        # Start Experiment
        self.assertIn(self.start_topic, self.mock_client.messages)
        self._adapter.withdraw()
        self._adapter.stop()
        mthread.join()

    def test_error_phase(self):
        self.initialize_experiment()
        text_watch_file = os.path.join(self._adapter._watcher._paths[0], self._adapter._watcher._filenames[0])
        if os.path.isfile(text_watch_file):
            os.remove(text_watch_file)
        time.sleep(1)

        topic = self._adapter._metadata_manager.error
        self.mock_client.subscribe(topic())
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)

        data = "Mock error string"
        self._adapter._processes[1].process_input(topic, data)

        timeout = 10
        cur_count = 0
        while topic() not in self.mock_client.messages:
            time.sleep(1)
            cur_count += 1
            if cur_count > timeout:
                self.fail("Message not recieved.")
        self._adapter.stop()
        mthread.join()
        self.assertIn(topic(), self.mock_client.messages)
        incoming_error = self.mock_client.messages[topic()]
        self.assertEqual(incoming_error[0]["type"], "HardwareStalledError")
        self.assertEqual(incoming_error[0]["severity"], "SeverityLevel.WARNING")
        self.assertIn(data, incoming_error[0]["message"])


if __name__ == "__main__":
    unittest.main()
