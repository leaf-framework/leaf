import ast
import os
import sys
import tempfile
import time
import unittest
import uuid
from threading import Thread

import pytest
import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.adapters.equipment_adapter import AbstractInterpreter, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.modules.input_modules.mqtt_external_event_watcher import MQTTExternalEventWatcher
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.phase_modules.control import ControlPhase
from leaf.modules.phase_modules.external_event_phase import logger
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.process_modules.discrete_module import DiscreteProcess
from leaf.register.metadata import MetadataManager
from leaf.registry.registry import discover_from_config
from leaf.start import adapters, run_adapters, stop_all_adapters
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir = os.path.dirname(os.path.realpath(__file__))
config_path = os.path.join(curr_dir, "..", "test_config.yaml")
test_file_dir = os.path.join(curr_dir, "..", "static_files")
text_watch_file = os.path.join(curr_dir, "tmp.txt")
mock_functional_adapter_path = os.path.join(curr_dir, "..", "mock_functional_adapter")

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


class MockEquipmentAdapter(EquipmentAdapter):
    def __init__(self, instance_data, equipment_data, fp, experiment_timeout=None):
        metadata_manager = MetadataManager()
        directory = os.path.dirname(fp)
        filename = os.path.basename(fp)
        watcher = FileWatcher(directory, metadata_manager, filenames=filename)
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        start_p = ControlPhase(metadata_manager.experiment.start)
        stop_p = ControlPhase(metadata_manager.experiment.stop)
        measure_p = MeasurePhase()
        details_p = ControlPhase(metadata_manager.details)

        metadata_manager.add_instance_data(instance_data)
        phase = [start_p, measure_p, stop_p, details_p]
        mock_process = [DiscreteProcess(output, phase)]
        error_holder = ErrorHolder()
        # This should be generated in start.py much like an output module.
        topics = [instance_data["instance_id"] + "/instructions"]
        external_watcher = MQTTExternalEventWatcher(
            broker=broker,
            metadata_manager=metadata_manager,
            topics=topics,
            port=port,
            username=un,
            password=pw,
        )
        super().__init__(
            equipment_data,
            watcher,
            output,
            mock_process,
            MockBioreactorInterpreter(),
            metadata_manager,
            error_holder=error_holder,
            experiment_timeout=experiment_timeout,
            external_watcher=external_watcher,
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
        unique_institute = "TestInstitute_" + unique_instance_id[:8]
        unique_department = "TestDepartment_" + unique_instance_id[:8]

        unique_file_name = f"TestBioreactor_{unique_instance_id}.txt"
        text_watch_file = os.path.join(self.temp_dir.name, unique_file_name)

        instance_data = {
            "instance_id": unique_instance_id,
            "institute": unique_institute,
            "department": unique_department,
        }
        equipment_data = {"adapter_id": "TestBioreactor_transmit_" + unique_instance_id}

        self.mock_client = MockBioreactorClient(broker, port, username=un, password=pw)

        self._adapter = MockEquipmentAdapter(instance_data, equipment_data, text_watch_file, **kwargs)

        self.details_topic = self._adapter._metadata_manager.details()
        self.start_topic = self._adapter._metadata_manager.experiment.start()
        self.stop_topic = self._adapter._metadata_manager.experiment.stop()

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

    def test_mock_adapter_takes_message(self):
        self.initialize_experiment()
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        timeout = 30
        cur_count = 0
        while not self._adapter.is_running():
            time.sleep(0.5)
            cur_count += 1
            if cur_count > timeout:
                self.fail("Unable to initialise.")
        unique_logger_name = logger.name
        with self.assertLogs(unique_logger_name, level="INFO") as logs:
            topics = self._adapter._external_watcher._topics
            for t in topics:
                self.mock_client.transmit(t, {"MOCK": "DATA"})
            time.sleep(2)
            self._adapter.stop()
            mthread.join()
            time.sleep(2)

        logged_dicts = []
        for log in logs.records:
            try:
                message = log.getMessage()
                logged_dict = ast.literal_eval(message)
                if isinstance(logged_dict, dict):
                    logged_dicts.append(logged_dict)
            except (ValueError, SyntaxError):
                continue

        expected_log = {
            "topic": self._adapter._external_watcher._topics[0],
            "data": '{"MOCK": "DATA"}',
            "actions_taken": None,
        }

        found_match = False

        for ld in logged_dicts:
            try:
                if all(k in ld and ld[k] == v for k, v in expected_log.items()):
                    if "timestamp" in ld:
                        found_match = True
                        break
            except Exception:
                continue

        self.assertTrue(found_match, "Expected log entry with valid timestamp not found.")

    @pytest.mark.timeout(60)
    def test_external_inputs_config(self):
        error_holder = ErrorHolder()
        write_file = "tmp1.csv"
        output = MQTT(
            broker,
            port,
            username=un,
            password=pw,
            clientid=None,
            error_holder=error_holder,
        )

        ins = [
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": f"{uuid.uuid4()}",
                        "institute": f"{uuid.uuid4()}",
                        "department": f"{uuid.uuid4()}"
                    },
                    "requirements": {"write_file": write_file},
                    "external_input": {
                        "plugin": "mqtt_external_event_watcher",
                        "broker": "localhost",
                        "port": 1883,
                        "topics": ["test_topic/external_action"],
                    },
                }
            }
        ]
        discover_from_config({"EQUIPMENT_INSTANCES": ins}, mock_functional_adapter_path)

        def _start() -> Thread:
            mthread = Thread(
                target=run_adapters,
                args=[ins, output, error_holder],
            )
            mthread.daemon = True
            mthread.start()
            return mthread

        def _stop(thread: Thread) -> None:
            stop_all_adapters()
            thread.join()
            time.sleep(10)

        test_topic = "test_topic/external_action"
        with self.assertLogs(logger.name, level="INFO") as logs:
            mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
            time.sleep(0.5)
            adapter_thread = _start()
            while len(adapters) == 0 or not adapters[0].is_running():
                continue
            mock_client.transmit(test_topic, {"MOCK": "DATA"})
            time.sleep(10)
            _stop(adapter_thread)

        logged_dicts = []
        for log in logs.records:
            try:
                message = log.getMessage()
                logged_dict = ast.literal_eval(message)
                if isinstance(logged_dict, dict):
                    logged_dicts.append(logged_dict)
            except (ValueError, SyntaxError):
                continue

        expected_log = {
            "topic": test_topic,
            "data": '{"MOCK": "DATA"}',
            "actions_taken": None,
        }

        found_match = False

        for ld in logged_dicts:
            try:
                if all(k in ld and ld[k] == v for k, v in expected_log.items()):
                    if "timestamp" in ld:
                        found_match = True
                        break
            except Exception:
                continue

        self.assertTrue(found_match, "Expected log entry with valid timestamp not found.")


if __name__ == "__main__":
    unittest.main()
