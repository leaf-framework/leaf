import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime
from threading import Thread

import pytest
import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.adapters.core_adapters.discrete_experiment_adapter import DiscreteExperimentAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
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


def _create_file(adapter) -> None:
    watch_file = os.path.join(adapter._watcher._paths[0], adapter._watcher._filenames[0])
    if os.path.isfile(watch_file):
        os.remove(watch_file)
    shutil.copyfile(initial_file, watch_file)
    # Wait for at least 2 polling cycles (1s each) plus processing time
    # to ensure the PollingObserver detects and processes the file creation
    time.sleep(3)


def _modify_file(adapter) -> None:
    watch_file = os.path.join(adapter._watcher._paths[0], adapter._watcher._filenames[0])
    with open(measurement_file) as src:
        content = src.read()
    with open(watch_file, "a") as dest:
        dest.write(content)
    # Wait for polling cycle plus processing time
    time.sleep(3)


def _delete_file(adapter) -> None:
    watch_file = os.path.join(adapter._watcher._paths[0], adapter._watcher._filenames[0])
    if os.path.isfile(watch_file):
        os.remove(watch_file)


class TestAdapterArray(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir1 = tempfile.TemporaryDirectory()
        self.temp_dir2 = tempfile.TemporaryDirectory()

        unique_id1 = str(uuid.uuid4())
        unique_id2 = str(uuid.uuid4())
        self.watch_file1 = os.path.join(self.temp_dir1.name, f"TestAdapterArray_{unique_id1}.csv")
        self.watch_file2 = os.path.join(self.temp_dir2.name, f"TestAdapterArray_{unique_id2}.csv")
        self.mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        self.output = MQTT(broker, port, username=un, password=pw)

        instance_data1 = {
            "instance_id": f"TestAdapterArray_{unique_id1}",
            "institute": f"Institute_{unique_id1}",
            "department": f"Department_{unique_id1}",
        }
        equipment_data = {
            "adapter_id": f"Equipment_{unique_id1}",
        }
        metadata_manager1 = MetadataManager()
        metadata_manager1.add_equipment_data(equipment_data)
        watcher1 = FileWatcher(self.temp_dir1.name, metadata_manager1, filenames=f"TestAdapterArray_{unique_id1}.csv")
        self._adapter = DiscreteExperimentAdapter(
            instance_data1, watcher1, self.output, MockBioreactorInterpreter(), metadata_manager=metadata_manager1
        )
        instance_data2 = {
            "instance_id": f"TestAdapterArray_{unique_id2}",
            "institute": f"Institute_{unique_id2}",
            "department": f"Department_{unique_id2}",
        }

        equipment_data2 = {
            "adapter_id": f"Equipment_{unique_id2}",
        }

        metadata_manager2 = MetadataManager()
        metadata_manager2.add_equipment_data(equipment_data2)
        watcher2 = FileWatcher(self.temp_dir2.name, metadata_manager2, filenames=f"TestAdapterArray_{unique_id2}.csv")
        self._adapter2 = DiscreteExperimentAdapter(
            instance_data2, watcher2, self.output, MockBioreactorInterpreter(), metadata_manager=metadata_manager2
        )
        self.adapter_array = [self._adapter, self._adapter2]

        for adapter in self.adapter_array:
            details_topic = adapter._metadata_manager.details()
            start_topic = adapter._metadata_manager.experiment.start()
            stop_topic = adapter._metadata_manager.experiment.stop()
            running_topic = adapter._metadata_manager.running()

            self.mock_client.flush(details_topic)
            time.sleep(0.2)
            self.mock_client.flush(start_topic)
            time.sleep(0.2)
            self.mock_client.flush(stop_topic)
            time.sleep(0.2)
            self.mock_client.flush(running_topic)
            time.sleep(1)
            wildcard_measure = adapter._metadata_manager.experiment.measurement()
            self.mock_client.subscribe(start_topic)
            time.sleep(0.2)
            self.mock_client.subscribe(stop_topic)
            time.sleep(0.2)
            self.mock_client.subscribe(running_topic)
            time.sleep(0.2)
            self.mock_client.subscribe(details_topic)
            time.sleep(0.2)
            self.mock_client.subscribe(wildcard_measure)
            time.sleep(1)

    def tearDown(self) -> None:
        for adapter in self.adapter_array:
            self._flush_topics(adapter)

        self.temp_dir1.cleanup()
        # self.temp_dir2.cleanup()

    def _run_adapters(self) -> list[Thread]:
        adapter_threads = []
        for adapter in self.adapter_array:
            thread = Thread(target=adapter.start)
            thread.daemon = True
            thread.start()
            adapter_threads.append(thread)
        return adapter_threads

    def _stop_adapters(self, adapter_threads: list[Thread]) -> None:
        for adapter in self.adapter_array:
            adapter.stop()
        for thread in adapter_threads:
            thread.join()

    def test_details(self) -> None:
        threads = self._run_adapters()
        time.sleep(1)
        self._stop_adapters(threads)
        for adapter in self.adapter_array:
            details_topic = adapter._metadata_manager.details()
            self.assertIn(details_topic, self.mock_client.messages)
            self.assertTrue(len(self.mock_client.messages[details_topic]) == 1)
            details_data = self.mock_client.messages[details_topic][0]

            self.assertIn("instance_id", details_data["instance"])
            self.assertEqual(
                adapter._metadata_manager.get_instance_data()["instance_id"],
                details_data["instance"]["instance_id"],
            )

    def test_start(self) -> None:
        threads = self._run_adapters()
        time.sleep(1)
        for adapter in self.adapter_array:
            _create_file(adapter)
        time.sleep(1)
        self._stop_adapters(threads)

        for adapter in self.adapter_array:
            start_topic = adapter._metadata_manager.experiment.start()
            self.assertIn(start_topic, self.mock_client.messages.keys())
            self.assertTrue(len(self.mock_client.messages[start_topic]) == 1)
            running_topic = adapter._metadata_manager.running()
            self.assertIn(running_topic, self.mock_client.messages)
            expected_run = "True"
            self.assertEqual(self.mock_client.messages[running_topic][0], expected_run)

    def test_stop(self) -> None:
        threads = self._run_adapters()
        time.sleep(1)
        for adapter in self.adapter_array:
            _create_file(adapter)
            time.sleep(1)
            _delete_file(adapter)
            time.sleep(1)
        time.sleep(1)
        self._stop_adapters(threads)

        for adapter in self.adapter_array:
            stop_topic = adapter._metadata_manager.experiment.stop()
            running_topic = adapter._metadata_manager.running()
            self.assertIn(stop_topic, self.mock_client.messages)
            self.assertEqual(len(self.mock_client.messages[stop_topic]), 1)
            timestamp_string = self.mock_client.messages[stop_topic][0]
            # Check if it is a valid timestamp
            self.assertTrue(datetime.strptime(timestamp_string, "%Y-%m-%d %H:%M:%S"), "The datetime should be valid")
            # self.assertIn("timestamp", self.mock_client.messages[stop_topic][0])

            self.assertIn(running_topic, self.mock_client.messages)
            expected_run = "False"
            self.assertEqual(self.mock_client.messages[running_topic][1], expected_run)

    def test_running(self) -> None:
        threads = self._run_adapters()
        time.sleep(1)
        for adapter in self.adapter_array:
            _create_file(adapter)
            time.sleep(1)
            _delete_file(adapter)
            time.sleep(1)
        time.sleep(1)
        self._stop_adapters(threads)

        for adapter in self.adapter_array:
            running_topic = adapter._metadata_manager.running()

            self.assertIn(running_topic, self.mock_client.messages)
            expected_run = "True"
            self.assertEqual(self.mock_client.messages[running_topic][0], expected_run)

    # @pytest.mark.skip(reason="Flaky test with excessive sleep statements (50s+ timeout) - needs refactoring")
    @pytest.mark.timeout(120)
    def test_logic(self) -> None:
        threads = self._run_adapters()
        self.mock_client.reset_messages()
        time.sleep(1)
        details_topics = []
        for adapter in self.adapter_array:
            details_topics.append(adapter._metadata_manager.details())

        for adapter1 in self.adapter_array:
            self._flush_topics(adapter1)

            details_topic = adapter1._metadata_manager.details()
            start_topic = adapter1._metadata_manager.experiment.start()
            stop_topic = adapter1._metadata_manager.experiment.stop()
            running_topic = adapter1._metadata_manager.running()
            self.assertTrue(len(self.mock_client.messages.keys()) == 2)
            self.assertIn(details_topic, self.mock_client.messages)
            exp_tp = adapter1._metadata_manager.experiment.measurement()
            self.mock_client.subscribe(exp_tp)
            time.sleep(1)
            _create_file(adapter1)

            self.assertIn(start_topic, self.mock_client.messages)
            self.assertIn(running_topic, self.mock_client.messages)
            self.assertEqual(len(self.mock_client.messages[start_topic]), 1)
            self.assertEqual(len(self.mock_client.messages[running_topic]), 1)
            self.assertTrue(self.mock_client.messages[running_topic][0] == "True")
            time.sleep(1)
            _modify_file(adapter1)
            time.sleep(5)
            _delete_file(adapter1)
            timeout = 50
            count = 0
            while len(self.mock_client.messages[running_topic]) != 2:
                time.sleep(1)
                count += 1
                if count > timeout:
                    self.fail()
            self.assertEqual(len(self.mock_client.messages[running_topic]), 2)
            self.assertTrue(self.mock_client.messages[running_topic][1] == "False")
            self.assertEqual(len(self.mock_client.messages[stop_topic]), 1)
            time.sleep(1)
            self._flush_topics(adapter1)
            time.sleep(2)

            for k in list(self.mock_client.messages.keys()):
                if k not in details_topics:
                    del self.mock_client.messages[k]
        self._stop_adapters(threads)

        self.mock_client.reset_messages()

    def _flush_topics(self, adapter: DiscreteExperimentAdapter) -> None:
        details_topic = adapter._metadata_manager.details()
        start_topic = adapter._metadata_manager.experiment.start()
        stop_topic = adapter._metadata_manager.experiment.stop()
        running_topic = adapter._metadata_manager.running()
        self.mock_client.flush(details_topic)
        self.mock_client.flush(start_topic)
        self.mock_client.flush(stop_topic)
        self.mock_client.flush(running_topic)


if __name__ == "__main__":
    unittest.main()
