import logging
import os
import shutil
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
from leaf.error_handler.exceptions import HardwareStalledError
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.phase_modules.control import ControlPhase
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.process_modules.discrete_module import DiscreteProcess
from leaf.register.metadata import MetadataManager
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir = os.path.dirname(os.path.realpath(__file__))

with open(os.path.join(curr_dir, "..", "test_config.yaml")) as file:
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


def _create_file(watch_file):
    if os.path.isfile(watch_file):
        os.remove(watch_file)
    shutil.copyfile(initial_file, watch_file)
    time.sleep(2)


def _modify_file(watch_file):
    with open(measurement_file) as src:
        content = src.read()
    with open(watch_file, "a") as dest:
        dest.write(content)
    time.sleep(2)


def _delete_file(watch_file):
    if os.path.isfile(watch_file):
        os.remove(watch_file)


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
        # The measurement fixture files used by these tests have ~285 rows;
        # the default maximum_message_size=1 would pace publishing at one
        # row per 0.1s (~28s total) on top of FileWatcher's debounce delay.
        # A large batch size keeps that in a single chunk for fast tests.
        measure_p = MeasurePhase(maximum_message_size=1000)
        details_p = ControlPhase(metadata_manager.details)

        metadata_manager.add_instance_data(instance_data)
        phase = [start_p, measure_p, stop_p, details_p]
        mock_process = [DiscreteProcess(output, phase)]
        error_holder = ErrorHolder()
        super().__init__(
            equipment_data,
            watcher,
            output,
            mock_process,
            MockBioreactorInterpreter(),
            metadata_manager,
            error_holder=error_holder,
            experiment_timeout=experiment_timeout,
        )


class TestEquipmentAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self._cleanup_loggers()

    def _cleanup_loggers(self):
        """Clean up all logger handlers to prevent file handle leaks between tests."""
        # Get all loggers and clear their handlers
        loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
        loggers.append(logging.getLogger())  # Add root logger

        for logger in loggers:
            # Close and remove all handlers
            for handler in logger.handlers[:]:
                try:
                    handler.flush()
                    handler.close()
                except (OSError, ValueError):
                    # Handler may already be closed
                    pass
                logger.removeHandler(handler)

            # Clear any disabled state
            logger.disabled = False

        # Also clear the root logger's handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            try:
                handler.flush()
                handler.close()
            except (OSError, ValueError):
                pass
            root.removeHandler(handler)

    def tearDown(self):
        try:
            if hasattr(self, "_adapter") and self._adapter:
                self._adapter.stop()
                # Give threads time to finish cleanup
                time.sleep(0.5)
        except Exception:
            pass

        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

        if hasattr(self, "mock_client"):
            self.mock_client.reset_messages()

        # Clean up loggers after test completion
        self._cleanup_loggers()

    def initialize_experiment(self, **kwargs):
        """
        Helper function to initialize a unique MockEquipmentAdapter
        instance with unique file paths and instance data.
        """

        unique_instance_id = str(uuid.uuid4())
        unique_organisation = "TestInstitute_"  # + unique_instance_id[:8]

        # .csv (not .txt) so FileWatcher parses the semicolon-delimited
        # fixture content into rows via _read_csv instead of returning it
        # as one opaque string, which MeasurePhase can't turn into a message.
        unique_file_name = f"TestBioreactor_{unique_instance_id}.csv"
        text_watch_file = os.path.join(self.temp_dir.name, unique_file_name)

        instance_data = {
            "instance_id": unique_instance_id,
            "organisation": unique_organisation,
            "department": "TestDepartment_",
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

    def wait_for_adapter_start(self, adapter):
        timeout = 30
        cur_count = 0
        while not adapter.is_running():
            time.sleep(1)
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

    def test_start(self):
        self.initialize_experiment()
        text_watch_file = os.path.join(self._adapter._watcher._paths[0], self._adapter._watcher._filenames[0])
        if self.start_topic in self.mock_client.messages:
            del self.mock_client.messages[self.start_topic]
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        _create_file(text_watch_file)
        time.sleep(2)
        self._adapter.stop()
        mthread.join()
        time.sleep(2)

        self.assertIn(self.start_topic, self.mock_client.messages)
        self.assertTrue(len(self.mock_client.messages[self.start_topic]) == 1)

    def test_stop(self):
        self.initialize_experiment()
        text_watch_file = os.path.join(self._adapter._watcher._paths[0], self._adapter._watcher._filenames[0])
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        _create_file(text_watch_file)
        self.mock_client.reset_messages()
        time.sleep(2)
        _delete_file(text_watch_file)
        time.sleep(2)
        self._adapter.stop()
        mthread.join()
        time.sleep(2)
        self.assertIn(self.stop_topic, self.mock_client.messages)
        self.assertTrue(len(self.mock_client.messages[self.stop_topic]) == 1)

        self.mock_client.messages = {}
        self.mock_client.unsubscribe(self.start_topic)
        self.mock_client.subscribe(self.start_topic)
        self.assertEqual(self.mock_client.messages, {})

    @pytest.mark.timeout(60)
    def test_update(self):
        self.initialize_experiment()
        text_watch_file = os.path.join(self._adapter._watcher._paths[0], self._adapter._watcher._filenames[0])
        if os.path.isfile(text_watch_file):
            os.remove(text_watch_file)
        time.sleep(1)

        exp_tp = self._adapter._metadata_manager.experiment.measurement(
            experiment_id=self._adapter._interpreter.id, measurement="unknown"
        )
        self.mock_client.subscribe(exp_tp)
        mthread = Thread(target=self._adapter.start)
        mthread.start()
        self.wait_for_adapter_start(self._adapter)
        _create_file(text_watch_file)
        time.sleep(2)
        _modify_file(text_watch_file)

        # FileWatcher's debounce/trailing-timer can delay delivery by up to
        # ~10s (see trailing_delay), so poll rather than assume a fixed sleep
        # is enough.
        deadline = time.time() + 20
        while time.time() < deadline and exp_tp not in self.mock_client.messages:
            time.sleep(1)

        _delete_file(text_watch_file)
        time.sleep(2)
        self._adapter.stop()
        mthread.join()
        time.sleep(2)
        self.assertIn(exp_tp, self.mock_client.messages)

    def test_exceptions(self):
        instance_data = {
            "instance_id": "test_exceptions_instance",
            "organisation": "test_exceptions_ins",
            "department": "test_exceptions_dep",
        }
        equipment_data = {"adapter_id": "test_exceptions_equip"}

        test_exp_tw_watch_file = os.path.join("tmp_exception.txt")
        adapter = MockEquipmentAdapter(instance_data, equipment_data, test_exp_tw_watch_file)

        mthread = Thread(target=adapter.start)
        mthread.start()
        with open(measurement_file) as src:
            content = src.read()
        with open(test_exp_tw_watch_file, "a") as dest:
            dest.write(content)
        self.wait_for_adapter_start(adapter)
        adapter.stop()
        mthread.join()

    def test_experiment_timeout(self):
        exp_timeout = 4
        unique_instance_id = str(uuid.uuid4())
        unique_organisation = "TestInstitute_"

        unique_file_name = f"TestBioreactor_{unique_instance_id}.txt"
        text_watch_file = os.path.join(self.temp_dir.name, unique_file_name)

        instance_data = {
            "instance_id": unique_instance_id,
            "organisation": unique_organisation,
            "department": "TestDepartment_",
        }

        equipment_data = {"adapter_id": "TestBioreactor_transmit_" + unique_instance_id}
        mock_client = MockBioreactorClient(broker, port, username=un, password=pw, remove_flush=True)

        _adapter = MockEquipmentAdapter(instance_data, equipment_data, text_watch_file, experiment_timeout=exp_timeout)

        details_topic = _adapter._metadata_manager.details()
        start_topic = _adapter._metadata_manager.experiment.start()
        stop_topic = _adapter._metadata_manager.experiment.stop()

        mock_client.flush(details_topic)
        mock_client.flush(start_topic)
        mock_client.flush(stop_topic)
        time.sleep(2)
        mock_client.subscribe(start_topic)
        time.sleep(0.5)
        mock_client.subscribe(stop_topic)
        time.sleep(0.5)
        mock_client.subscribe(details_topic)
        time.sleep(2)

        if os.path.isfile(text_watch_file):
            os.remove(text_watch_file)
            time.sleep(1)

        mthread = Thread(target=_adapter.start)
        unique_logger_name = f"leaf.adapters.equipment_adapter.{_adapter._metadata_manager.get_instance_id()}"
        expected_exceptions = [HardwareStalledError("Experiment timeout")]
        with self.assertLogs(unique_logger_name, level="WARNING") as logs:
            mthread.start()
            watcher_timeout = 10
            watcher_count = 0
            while not _adapter._watcher.is_running():
                time.sleep(1)
                watcher_count += 1
                if watcher_count > watcher_timeout:
                    self.fail("Couldnt start watcher to test.")
            _create_file(text_watch_file)
            time.sleep(1)
            _modify_file(text_watch_file)
            timeout = 30
            start_time = time.time()

            while len(expected_exceptions) > 0 and (time.time() - start_time < timeout):
                for log in logs.records:
                    exc_type, exc_value, exc_traceback = log.exc_info
                    print(exc_type, exc_value)
                    for exp_exc in list(expected_exceptions):
                        if (
                            type(exp_exc) == exc_type
                            and exp_exc.severity == exc_value.severity
                            and exp_exc.args == exc_value.args
                        ):
                            expected_exceptions.remove(exp_exc)
                time.sleep(0.1)
            self.assertEqual(
                list(mock_client.messages.keys()),
                [_adapter._metadata_manager.details(), _adapter._metadata_manager.experiment.start()],
            )
            _adapter.stop()
            mthread.join()
            if len(expected_exceptions) > 0:
                self.fail("Test timed out waiting for expected exceptions.")
        mock_client.reset_messages()


if __name__ == "__main__":
    unittest.main()
