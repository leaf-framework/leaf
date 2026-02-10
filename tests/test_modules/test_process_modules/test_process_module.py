import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from threading import Thread

import yaml

from leaf.utility.logger.logger_utils import get_logger

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf_register.metadata import MetadataManager

from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.phase_modules.start import StartPhase
from leaf.modules.phase_modules.stop import StopPhase
from leaf.modules.process_modules.continous_module import ContinousProcess
from leaf.modules.process_modules.discrete_module import DiscreteProcess
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir = os.path.dirname(os.path.realpath(__file__))

logger = get_logger(__name__, log_file="test_process_module.log")

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

test_file_dir = os.path.join(curr_dir, "..", "..", "static_files")
initial_file = os.path.join(test_file_dir, "biolector1_metadata.csv")
measurement_file = os.path.join(test_file_dir, "biolector1_measurement.csv")


def _create_file(text_watch_file):
    shutil.copyfile(initial_file, text_watch_file)
    time.sleep(1)


def _modify_file(text_watch_file):
    with open(measurement_file) as src:
        content = src.read()
    with open(text_watch_file, "a") as dest:
        dest.write(content)
    time.sleep(1)


def _delete_file(text_watch_file):
    if os.path.isfile(text_watch_file):
        os.remove(text_watch_file)


def _run_change(func, text_watch_file) -> None:
    mthread = Thread(target=func, args=(text_watch_file,))
    mthread.start()
    mthread.join()


class MockInterpreter(AbstractInterpreter):
    def __init__(self, experiment_id):
        super().__init__()
        self.id = experiment_id

    def metadata(self, data):
        return [{"message": data}] if isinstance(data, (str, int, float, bool)) else [data]

    def measurement(self, data):
        return [{"message": data}] if isinstance(data, (str, int, float, bool)) else [data]

    def simulate(self):
        return super().simulate()


class TestContinousProcess(unittest.TestCase):
    def setUp(self) -> None:
        # Use a temporary file for each test to avoid interference
        custom_tmp_dir = os.path.join(tempfile.gettempdir(), "leaf_temp")
        os.makedirs(custom_tmp_dir, exist_ok=True)

        self.text_watch_file = tempfile.NamedTemporaryFile(delete=False, dir=custom_tmp_dir).name
        # Create the watch file in the custom temporary directory
        if os.path.isfile(self.text_watch_file):
            os.remove(self.text_watch_file)
        print(f"Using temporary file: {self.text_watch_file}")
        with open(self.text_watch_file, "w") as f:
            f.write("")

        self.mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        self.ins_id = "TestContinousProcess_" + str(uuid.uuid4())
        self.adapter_id = str(uuid.uuid4())
        self.instance_id = str(uuid.uuid4())
        self.mock_client.subscribe(f"{self.ins_id}/{self.adapter_id}/{self.instance_id}/#")

        self.metadata_manager = MetadataManager()
        self.metadata_manager.add_equipment_value("adapter_id", self.adapter_id)
        self.metadata_manager.add_instance_value("institute", self.ins_id)
        self.metadata_manager.add_instance_value("instance_id", self.instance_id)

        directory = os.path.dirname(self.text_watch_file)
        filename = os.path.basename(self.text_watch_file)
        self.watcher = FileWatcher(directory, self.metadata_manager, filenames=filename)
        output = MQTT(broker, port, username=un, password=pw, clientid=None)

        # output.client.publish(f"{ins_id}/{adapter_id}/{instance_id}/status", "online")

        self._phase = MeasurePhase(self.metadata_manager)
        self._module = ContinousProcess(output, self._phase)

        self._mock_experiment = "test_experiment_id"
        self._mock_measurement = "test_measurement_id"
        self._module.set_interpreter(MockInterpreter(self._mock_experiment))
        self.watcher.add_callback(self._mock_update)

    def tearDown(self) -> None:
        self.watcher.stop()
        time.sleep(1)
        if os.path.isfile(self.text_watch_file):
            print(f"Removing temporary file: {self.text_watch_file}")
            os.remove(self.text_watch_file)
        self.mock_client = None

    def _mock_update(self, topic, data) -> None:
        print(f"Processing input for topic: {topic} with data: {data[:100]}")
        self._module.process_input(topic, data)

    def test_continous_process(self) -> None:
        self.watcher.start()
        _run_change(_create_file, self.text_watch_file)
        time.sleep(1)
        _run_change(_modify_file, self.text_watch_file)
        time.sleep(1)
        while len(self.mock_client.messages) < 1:
            logger.debug("Waiting for messages...")
            time.sleep(1)
        for k, v in self.mock_client.messages.items():
            print(f"Received message on topic {k}: {v}")
            if k.startswith(f"{self.ins_id}/{self.adapter_id}/{self.instance_id}"):
                if (
                    self.metadata_manager.experiment.measurement(
                        experiment_id=self._mock_experiment, measurement="unknown"
                    )
                    == k
                ):
                    print(f"Measurement phase message matched: {k}")
                    break
                else:
                    print(f"Expected measurement phase message not found: {k}")
        else:
            self.fail()


class TestDiscreteProcess(unittest.TestCase):
    def setUp(self) -> None:
        custom_tmp_dir = os.path.join(tempfile.gettempdir(), "leaf_temp")
        os.makedirs(custom_tmp_dir, exist_ok=True)

        self.text_watch_file = tempfile.NamedTemporaryFile(delete=False, dir=custom_tmp_dir).name

        self.mock_client = MockBioreactorClient(broker, port, username=un, password=pw)
        self.ins_id = str(uuid.uuid4())
        self.adapter_id = str(uuid.uuid4())
        self.instance_id = str(uuid.uuid4())
        self.mock_client.subscribe(f"{self.ins_id}/{self.adapter_id}/{self.instance_id}/#")

        self.metadata_manager = MetadataManager()
        self.metadata_manager.add_equipment_value("adapter_id", self.adapter_id)
        self.metadata_manager.add_instance_value("institute", self.ins_id)
        self.metadata_manager.add_instance_value("instance_id", self.instance_id)

        directory = os.path.dirname(self.text_watch_file)
        filename = os.path.basename(self.text_watch_file)
        self.watcher = FileWatcher(directory, self.metadata_manager, filenames=filename)
        output = MQTT(broker, port, username=un, password=pw, clientid=None)

        start_p = StartPhase(self.metadata_manager)
        stop_p = StopPhase(self.metadata_manager)
        self._measure_p = MeasurePhase(self.metadata_manager)

        phases = [start_p, self._measure_p, stop_p]
        self._module = DiscreteProcess(output, phases)
        self._mock_experiment = "test_experiment_id"
        self._mock_measurement = "test_measurement_id"
        self._module.set_interpreter(MockInterpreter(self._mock_experiment))
        self.watcher.add_callback(self._module.process_input)

    def tearDown(self) -> None:
        self.watcher.stop()
        time.sleep(1)
        if os.path.isfile(self.text_watch_file):
            os.remove(self.text_watch_file)
        self.mock_client = None

    def test_discrete_process(self):
        if os.path.isfile(self.text_watch_file):
            os.remove(self.text_watch_file)
            time.sleep(0.5)
        self.watcher.start()
        time.sleep(1)
        _run_change(_create_file, self.text_watch_file)
        time.sleep(1)
        _run_change(_modify_file, self.text_watch_file)
        time.sleep(1)
        _run_change(_delete_file, self.text_watch_file)
        time.sleep(1)

        fail = True

        for k, v in self.mock_client.messages.items():
            print(f"Received message on topic {k}: {v}")
            if k.startswith(f"{self.ins_id}/{self.adapter_id}/{self.instance_id}") and k.endswith("start"):
                if self.metadata_manager.experiment.start() == k:
                    print(f"Start phase message matched: {k}")
                    fail = False
                    break
        else:
            self.fail()

        if fail:
            self.fail()

        fail = True
        for k, v in self.mock_client.messages.items():
            # These modifications are necessary to match the expected topic structure when running tests in parallel
            if k.startswith(f"{self.ins_id}/{self.adapter_id}/{self.instance_id}"):
                if (
                    self.metadata_manager.experiment.measurement(
                        experiment_id=self._mock_experiment, measurement="unknown"
                    )
                    == k
                ):
                    print(f"Measurement phase message matched: {k}")
                    fail = False
                    break
        else:
            self.fail()

        if fail:
            self.fail()

        fail = True

        for k, v in self.mock_client.messages.items():
            if k.startswith(f"{self.ins_id}/{self.adapter_id}/{self.instance_id}") and k.endswith("stop"):
                if self.metadata_manager.experiment.stop() == k:
                    print(f"Stop phase message matched: {k}")
                    fail = False
                    break
        else:
            self.fail()

        if fail:
            self.fail()
