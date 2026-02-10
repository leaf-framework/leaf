import errno
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from csv import Error as csv_error
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, mock_open, patch

import paho.mqtt.client as mqtt
import pytest
import yaml
from paho.mqtt.client import CONNACK_REFUSED_PROTOCOL_VERSION

from leaf.modules.output_modules.sql import SQL

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf_register.metadata import MetadataManager

from leaf import start
from leaf.adapters.equipment_adapter import AbstractInterpreter, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import (
    AdapterBuildError,
    ClientUnreachableError,
    InputError,
    InterpreterError,
    SeverityLevel,
)
from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf.modules.output_modules.file import FILE
from leaf.modules.output_modules.keydb import KEYDB
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.phase_modules.control import ControlPhase
from leaf.modules.phase_modules.measure import MeasurePhase
from leaf.modules.process_modules.continous_module import ContinousProcess
from leaf.modules.process_modules.discrete_module import DiscreteProcess
from leaf.registry.registry import discover_from_config
from leaf.start import process_instance, run_adapters, stop_all_adapters
from leaf.utility.running_utilities import build_output_module
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir = os.path.dirname(os.path.realpath(__file__))

with open(os.path.join(curr_dir, "test_config.yaml")) as file:
    config = yaml.safe_load(file)

broker = config["OUTPUTS"][0]["broker"]
port = int(config["OUTPUTS"][0]["port"])
try:
    un = config["OUTPUTS"][0]["username"]
    pw = config["OUTPUTS"][0]["password"]
except (KeyError, IndexError):
    un = None
    pw = None

watch_file = os.path.join("tmp.txt")
curr_dir = os.path.dirname(os.path.realpath(__file__))
test_file_dir = os.path.join(curr_dir, "static_files")
initial_file = os.path.join(test_file_dir, "biolector1_metadata.csv")
measurement_file = os.path.join(test_file_dir, "biolector1_measurement.csv")
all_data_file = os.path.join(test_file_dir, "biolector1_full.csv")
text_watch_file = os.path.join("tmp.txt")
mock_functional_adapter_path = os.path.join(curr_dir, "mock_functional_adapter")


class MockBioreactorInterpreter(AbstractInterpreter):
    def __init__(self) -> None:
        super().__init__()
        self.id = "test_bioreactor"

    def metadata(self, data):
        return data

    def measurement(self, data):
        return data

    def simulate(self) -> None:
        return


class MockEquipment(EquipmentAdapter):
    def __init__(self, instance_data, equipment_data, fp, error_holder=None) -> None:
        metadata_manager = MetadataManager()
        directory = os.path.dirname(fp)
        filename = os.path.basename(fp)
        watcher = FileWatcher(directory, metadata_manager, error_holder=error_holder, filenames=filename)
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        start_p = ControlPhase(metadata_manager.experiment.start, metadata_manager)
        stop_p = ControlPhase(metadata_manager.experiment.stop, metadata_manager)
        measure_p = MeasurePhase(metadata_manager)
        details_p = ControlPhase(metadata_manager.details, metadata_manager)

        phase = [start_p, measure_p, stop_p, details_p]
        mock_process = [DiscreteProcess(output, phase)]
        metadata_manager.add_instance_data(instance_data)
        super().__init__(
            equipment_data,
            watcher,
            output,
            mock_process,
            MockBioreactorInterpreter(),
            metadata_manager,
            error_holder=error_holder,
        )


class TestExceptionsInit(unittest.TestCase):
    def setUp(self) -> None:
        # Reset output module failure counter to prevent cross-test contamination
        OutputModule.reset_failure_count()
        pass

    def test_start_get_output_module_not_found(self) -> None:
        config = {
            "OUTPUTS": [
                {
                    "plugin": "MQTTT",
                    "broker": "localhost",
                    "port": 1883,
                    "fallback": "KEYDB",
                },
                {
                    "plugin": "KEYDB",
                    "host": "localhost",
                    "port": 6379,
                    "db": 0,
                    "fallback": "FILE",
                },
                {"plugin": "FILE", "filename": "local.json", "fallback": None},
            ],
        }
        with self.assertRaises(AdapterBuildError):
            build_output_module(config, None)

    def test_start_get_output_fallback_not_found(self) -> None:
        config = {
            "OUTPUTS": [
                {
                    "plugin": "MQTT",
                    "broker": "localhost",
                    "port": 1883,
                    "fallback": "KEYDBB",
                },
                {
                    "plugin": "KEYDB",
                    "host": "localhost",
                    "port": 6379,
                    "db": 0,
                    "fallback": "FILE",
                },
                {"plugin": "FILE", "filename": "local.json", "fallback": None},
            ],
        }
        with self.assertRaises(AdapterBuildError):
            build_output_module(config, None)

    def test_start_get_output_invalid_params(self) -> None:
        config = {
            "OUTPUTS": [
                {
                    "plugin": "MQTT",
                    "port": 1883,
                    "fallback": "KEYDB",
                },
                {
                    "plugin": "KEYDB",
                    "host": "localhost",
                    "port": 6379,
                    "db": 0,
                    "fallback": "FILE",
                },
                {"plugin": "FILE", "filename": "local.json", "fallback": None},
            ],
        }
        with self.assertRaises(AdapterBuildError):
            build_output_module(config, None)

    def test_startprocess_instance_not_found(self) -> None:
        config = {
            "adapter": "BioLector123",
            "data": {"instance_id": "biolector_devonshire10", "institute": "NCL"},
            "requirements": {"write_file": "tmp1.csv"},
        }
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        with self.assertRaises(AdapterBuildError):
            process_instance(config, output)

    def test_startprocess_instance_no_requirements(self) -> None:
        config = {
            "adapter": "BioLector1",
            "data": {"instance_id": "biolector_devonshire10", "institute": "NCL"},
            "requirements": {},
        }
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        with self.assertRaises(AdapterBuildError):
            process_instance(config, output)

    def test_startprocess_instance_missing_id(self) -> None:
        config = {
            "adapter": "BioLector1",
            "data": {"institute": "NCL"},
            "requirements": {"write_file": "tmp1.csv"},
        }
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        with self.assertRaises(AdapterBuildError):
            process_instance(config, output)

    def test_file_watcher_invalid_filepath(self) -> None:
        filepath = None
        metadata_manager = MetadataManager()
        with self.assertRaises(AdapterBuildError):
            FileWatcher(filepath, metadata_manager)

    def test_output_module_connect(self) -> None:
        f_broker = "Unknown_broker_addr"
        with self.assertRaises(ClientUnreachableError):
            MQTT(f_broker, clientid=None)

    def test_raise_continous_discrete_process(self) -> None:
        metadata_manager = MetadataManager()
        output = MQTT(broker, port, username=un, password=pw, clientid=None)
        start_p = ControlPhase(output, metadata_manager.experiment.start, metadata_manager)
        stop_p = ControlPhase(output, metadata_manager.experiment.stop, metadata_manager)
        measure_p = MeasurePhase(metadata_manager)

        phase = [start_p, measure_p, stop_p]

        def _init_cont_proc() -> None:
            ContinousProcess(output, phase)

        def _init_disc_proc() -> None:
            DiscreteProcess(output, [phase[0]])

        self.assertRaises(AdapterBuildError, _init_cont_proc)
        self.assertRaises(AdapterBuildError, _init_disc_proc)


class TestExceptionsGeneral(unittest.TestCase):
    def setUp(self) -> None:
        # Reset output module failure counter to prevent cross-test contamination
        OutputModule.reset_failure_count()

        self.error_holder = MagicMock()
        self.broker = "test_broker"
        self.port = 1883
        self.host = "localhost"
        self.mqtt_client = MQTT(broker=self.broker, port=self.port, error_holder=self.error_holder)
        self.keydb_client = KEYDB(host=self.host, port=self.port, error_holder=self.error_holder)
        self.file_client = FILE(filename="test.json", error_holder=self.error_holder)

    def tearDown(self) -> None:
        # Reset output module failure counter after test completion
        OutputModule.reset_failure_count()

    @patch("leaf.modules.output_modules.mqtt.mqtt.Client.connect")
    def test_mqtt_module_cant_connect_init(self, mock_connect: MagicMock) -> None:
        mock_connect.side_effect = ClientUnreachableError("Broker unreachable")
        with self.assertRaises(ClientUnreachableError):
            self.mqtt_client.__init__(broker=self.broker, port=self.port, error_holder=self.error_holder)
        self.error_holder.add_error.assert_called_once()

    @patch("leaf.modules.output_modules.mqtt.MQTT._handle_exception")
    @patch("leaf.modules.output_modules.mqtt.mqtt.Client.publish")
    def test_mqtt_module_cant_transmit(self, mock_publish, mock_handle_exception) -> None:
        mock_publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
        self.mqtt_client.transmit("test/topic", "message")

        self.assertEqual(mock_handle_exception.call_count, 1)
        first_call = mock_handle_exception.call_args_list[0]
        self.assertIn("no output mechanisms available", str(first_call))

    @patch("leaf.modules.output_modules.mqtt.mqtt.Client.publish")
    def test_mqtt_module_cant_flush(self, mock_publish) -> None:
        mock_publish.side_effect = ClientUnreachableError("No connection")

        with self.assertRaises(ClientUnreachableError):
            self.mqtt_client.flush("test/topic")
        self.error_holder.add_error.assert_called_once()

    @patch("leaf.modules.output_modules.mqtt.MQTT._handle_exception")
    def test_mqtt_module_on_connect_invalid_input(self, mock_handle_exception) -> None:
        self.mqtt_client.on_connect("test_client", None, None, rc=CONNACK_REFUSED_PROTOCOL_VERSION)
        mock_handle_exception.assert_called_once()
        self.assertIn(
            "Connection refused: Unacceptable protocol version",
            str(mock_handle_exception.call_args[0][0]),
        )

    @patch("leaf.modules.output_modules.mqtt.mqtt.Client.connect")
    def test_mqtt_module_on_connect_cant_reach_broker(self, mock_connect) -> None:
        mock_connect.side_effect = ClientUnreachableError("Server unavailable")
        with self.assertRaises(ClientUnreachableError):
            self.mqtt_client.__init__(broker=self.broker, port=self.port, error_holder=self.error_holder)

    @patch("leaf.modules.output_modules.keydb.KEYDB._handle_redis_error")
    @patch("leaf.modules.output_modules.keydb.redis.StrictRedis")
    def test_keydb_connect_cant_access_client(self, mock_redis, mock_handle_error) -> None:
        mock_redis.side_effect = ClientUnreachableError("Connection to KeyDB failed")
        with self.assertRaises(ClientUnreachableError):
            self.keydb_client.connect()

    @patch("leaf.modules.output_modules.mqtt.logger")
    def test_mqtt_module_on_disconnect_logs_warning(self, mock_logger: MagicMock) -> None:
        """Test that unexpected disconnect logs a warning (paho handles reconnection)."""
        self.error_holder.reset_mock()
        self.mqtt_client.on_disconnect(client="test_client", userdata=None, flags=None, rc=2)
        # Should log a warning about paho auto-reconnecting
        mock_logger.warning.assert_called_once()
        self.assertIn("paho will auto-reconnect", mock_logger.warning.call_args[0][0])

    @patch("leaf.modules.output_modules.file.open", new_callable=mock_open)
    @patch("leaf.modules.output_modules.file.os.path.exists", return_value=True)
    def test_file_transmit_cant_access_file(self, mock_exists, mock_open_file) -> None:
        self.error_holder.reset_mock()  # Reset previous error calls
        mock_open_file.side_effect = OSError("Unable to open file")

        # Attempt to transmit data and expect fallback mechanism
        self.file_client.transmit("test_topic", "test_data")

        # Verify the error was handled, called twice due to fallback attempt
        self.assertEqual(self.error_holder.add_error.call_count, 2)

    @patch("leaf.modules.output_modules.file.open", new_callable=mock_open)
    def test_file_transmit_write_error(self, mock_open_file) -> None:
        self.error_holder.reset_mock()  # Reset previous error calls
        # Simulate an OSError during file write (e.g., disk full, permission denied)
        mock_open_file.side_effect = OSError("Unable to write to file")

        # Attempt to transmit data and expect fallback mechanism
        self.file_client.transmit("test_topic", "test_data")

        # Verify the error was handled (called twice due to fallback attempt)
        assert self.error_holder.add_error.call_count == 2

    def test_file_transmit_non_serializable_data(self) -> None:
        self.error_holder.reset_mock()  # Reset previous error calls

        # Create a non-JSON-serializable object (e.g., a set or custom class)
        class NonSerializable:
            pass

        non_serializable_data = NonSerializable()

        # Attempt to transmit non-serializable data
        result = self.file_client.transmit("test_topic", non_serializable_data)

        # Should return False (both FILE and fallback can't serialize non-JSON data)
        self.assertFalse(result)
        # Verify the error was handled (called twice: primary + fallback)
        assert self.error_holder.add_error.call_count >= 2

    @patch("leaf.modules.output_modules.file.open", new_callable=mock_open)
    @patch("leaf.modules.output_modules.file.os.path.exists", return_value=True)
    def test_file_retrieve_cant_access_file(self, mock_exists, mock_open_file) -> None:
        self.error_holder.reset_mock()  # Reset previous error calls
        # Simulate an OSError during file retrieval
        mock_open_file.side_effect = OSError("Unable to access file")

        # Attempt to retrieve data
        result = self.file_client.retrieve("test_topic")

        # Assert that None is returned due to error and error is recorded
        self.assertIsNone(result)
        self.error_holder.add_error.assert_called_once()

    @patch("json.load", side_effect=json.JSONDecodeError("Invalid JSON", doc="", pos=0))
    @patch("leaf.modules.output_modules.file.open", new_callable=mock_open)
    def test_file_retrieve_invalid_json(self, mock_open_file, mock_json_load) -> None:
        # Attempt to retrieve data
        result = self.file_client.retrieve("test_topic")

        # Assert that [] is returned due to error and error is recorded
        self.assertEqual(result, [])
        self.error_holder.add_error.assert_called_once()

    @pytest.mark.timeout(60)
    def test_start_handler_no_fallback(self) -> None:
        # Reset failure counter and temporarily increase threshold for this test
        OutputModule.reset_failure_count()
        original_threshold = OutputModule._max_failures_before_reboot
        OutputModule._max_failures_before_reboot = 100

        try:
            error_holder = ErrorHolder()
            output = MQTT(
                broker,
                port,
                username=un,
                password=pw,
                clientid=None,
                error_holder=error_holder,
            )

            write_dir = "test"
            if not os.path.isdir(write_dir):
                os.mkdir(write_dir)
            write_file = os.path.join(write_dir, "tmp1.csv")

            ins = [
                {
                    "equipment": {
                        "adapter": "MockFunctionalAdapter",
                        "data": {
                            "instance_id": f"{uuid.uuid4()}",
                            "institute": f"{uuid.uuid4()}",
                        },
                        "requirements": {"write_file": write_file},
                    }
                }
            ]
            discover_from_config({"EQUIPMENT_INSTANCES": ins}, mock_functional_adapter_path)

            def _start() -> Thread:
                mthread = Thread(target=run_adapters, args=[ins, output, error_holder])
                mthread.daemon = True
                mthread.start()
                return mthread

            def _stop(thread: Thread) -> None:
                stop_all_adapters()
                time.sleep(10)

            try:
                with self.assertLogs(start.__name__, level="WARNING") as logs:
                    adapter_thread = _start()
                    time.sleep(2)
                    while output.client.is_connected():
                        output.disconnect()
                        continue
                    no_op_top = "test/test/"
                    output.fallback(no_op_top, {})
                    time.sleep(15)
                    output.disconnect()
                    time.sleep(1)
                    _stop(adapter_thread)
            finally:
                _stop(adapter_thread)

            # Define expected exceptions with type, severity, and message prefix
            expected_exceptions = [
                {
                    "type": ClientUnreachableError,
                    "severity": SeverityLevel.WARNING,
                    "message_prefix": "Cannot connect or reach client: Cannot store data, no output mechanisms available.",
                }
            ]

            self.assertTrue(len(logs.records) > 0)
            found_exceptions = []

            for log in logs.records:
                exc_type, exc_value, exc_traceback = log.exc_info
                if exc_value:  # Ensure there's an actual exception
                    message = exc_value.args[0] if exc_value.args else ""
                    print(
                        f"Checking exception: {exc_type.__name__}, severity: {getattr(exc_value, 'severity', 'N/A')}, message: {message}"
                    )

                    for expected in expected_exceptions:
                        if (
                            exc_type == expected["type"]
                            and hasattr(exc_value, "severity")
                            and exc_value.severity == expected["severity"]
                            and message.startswith(expected["message_prefix"])
                        ):
                            print(f"Matched expected exception: {expected}")
                            found_exceptions.append(expected)
                            break

            # Ensure we found at least one matching exception (allowing for multiple occurrences)
            unique_found = {(e["type"].__name__, e["severity"], e["message_prefix"]) for e in found_exceptions}
            expected_unique = {(e["type"].__name__, e["severity"], e["message_prefix"]) for e in expected_exceptions}

            missing_exceptions = expected_unique - unique_found
            self.assertEqual(len(missing_exceptions), 0, f"Missing expected exceptions: {missing_exceptions}")
        finally:
            # Restore original threshold
            OutputModule._max_failures_before_reboot = original_threshold
            OutputModule.reset_failure_count()

    def test_start_handler_no_connection(self) -> None:
        write_dir = Path(os.path.dirname(os.path.realpath(__file__))) / ".." / "testing_data" / str(uuid.uuid4())
        error_holder = ErrorHolder()
        if not os.path.isdir(write_dir):
            os.makedirs(write_dir, exist_ok=False)
        write_file = os.path.join(write_dir, "tmp1.csv")
        file_fn = os.path.join(write_dir, "file_fn.txt")
        file = FILE(file_fn)
        fake_broker = "fake_mqtt_broker_"
        output = MQTT(
            fake_broker,
            clientid=None,
            error_holder=error_holder,
            fallback=file,
        )

        ins = [
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": f"{uuid.uuid4()}",
                        "institute": f"{uuid.uuid4()}",
                    },
                    "requirements": {"write_file": write_file},
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
            time.sleep(10)

        with self.assertLogs(start.__name__, level="WARNING") as logs:
            adapter_thread = _start()
            timeout = 50
            cur_count = 0
            while output.is_enabled():
                time.sleep(1)
                cur_count += 1
                if cur_count > timeout:
                    self.fail()
                output.transmit("test_topic")

            _stop(adapter_thread)

        expected_exceptions = [
            ClientUnreachableError(
                "Error connecting to broker: [Errno -3] Temporary failure in name resolution",
                SeverityLevel.WARNING,
            ),
        ]
        expected_logs = ["Disabling client MQTT."]
        self.assertIsInstance(output._enabled, type(time.time()))
        self.assertTrue(len(logs.records) > 0)
        for log in logs.records:
            exc_type, exc_value, exc_traceback = log.exc_info
            for exp_log in list(expected_logs):
                if exp_log == log.getMessage():
                    expected_logs.remove(exp_log)
            for exp_exc in list(expected_exceptions):
                if (
                    type(exp_exc) == exc_type
                    and exp_exc.severity == exc_value.severity
                    and exp_exc.args == exc_value.args
                ):
                    expected_exceptions.remove(exp_exc)

        # With a fake broker at least one exception is expected?
        self.assertTrue(len(expected_exceptions) <= 1)
        self.assertEqual(len(expected_logs), 0)

    @pytest.mark.skip(reason="Flaky in CI due to resource contention and timing issues - needs refactoring")
    @pytest.mark.timeout(60)
    @pytest.mark.forked  # Explicitly mark for forking (overrides no-fork marker if needed)
    def test_start_handler_multiple_adapter_critical(self) -> None:
        error_holder = ErrorHolder()
        write_dir = Path(os.path.dirname(os.path.realpath(__file__))) / ".." / "testing_data" / str(uuid.uuid4())
        if not os.path.isdir(write_dir):
            os.makedirs(write_dir, exist_ok=False)
        write_file1 = os.path.join(write_dir, "tmp1.csv")
        write_file2 = os.path.join(write_dir, "tmp2.csv")
        file_fn = os.path.join(write_dir, "file_fn.txt")
        file = SQL(file_fn)
        output = MQTT(
            broker,
            port,
            username=un,
            password=pw,
            clientid=None,
            error_holder=error_holder,
            fallback=file,
        )

        ins = [
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": f"{uuid.uuid4()}",
                        "institute": f"{uuid.uuid4()}",
                    },
                    "requirements": {"write_file": write_file1},
                }
            },
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": f"{uuid.uuid4()}",
                        "institute": f"{uuid.uuid4()}",
                    },
                    "requirements": {"write_file": write_file2},
                }
            },
        ]
        discover_from_config({"EQUIPMENT_INSTANCES": ins}, mock_functional_adapter_path)

        def _start() -> None:
            mthread = Thread(target=run_adapters, args=[ins, output, error_holder])
            mthread.daemon = True
            mthread.start()
            return mthread

        def _stop(thread) -> None:
            stop_all_adapters()
            time.sleep(10)

        with self.assertLogs(start.__name__, level="ERROR") as captured:
            adapter_thread = _start()
            time.sleep(10)
            exception = ClientUnreachableError(
                "test_multiple_adapter_reset_test_exception",
                severity=SeverityLevel.CRITICAL,
            )
            error_holder.add_error(exception)
            time.sleep(1)
            # Wait until the error string appears in logs (up to a timeout)
            start_time = time.time()
            found_log = False
            while time.time() - start_time < 10:  # 10-second timeout
                # Check if the log message is in any of the captured logs
                if any(
                    "test_multiple_adapter_reset_test_exception" in record.getMessage() for record in captured.records
                ):
                    found_log = True
                    break
                time.sleep(0.1)
            _stop(adapter_thread)

        self.assertTrue(found_log, "Timed out waiting for the critical error to be logged.")

        expected_exceptions = [exception]
        self.assertTrue(len(captured.records) > 0)
        for log in captured.records:
            exc_type, exc_value, exc_traceback = log.exc_info
            for exp_exc in list(expected_exceptions):
                if (
                    type(exp_exc) == exc_type
                    and exp_exc.severity == exc_value.severity
                    and exp_exc.args == exc_value.args
                ):
                    expected_exceptions.remove(exp_exc)

        self.assertEqual(len(expected_exceptions), 0)


class TestExceptionsAdapterSpecific(unittest.TestCase):
    def setUp(self) -> None:
        # Reset output module failure counter to prevent cross-test contamination
        OutputModule.reset_failure_count()

        self.temp_dir = tempfile.TemporaryDirectory()
        unique_instance_id = str(uuid.uuid4())
        unique_file_name = f"TestBioreactor_{unique_instance_id}.txt"

        self.file_path = os.path.join(self.temp_dir.name, unique_file_name)
        with open(self.file_path, "w"):
            pass

        self.metadata_manager = MagicMock()
        self.file_watcher = FileWatcher(
            self.temp_dir.name, metadata_manager=self.metadata_manager, filenames=unique_file_name, use_polling=False
        )  # Use Observer (not PollingObserver) so mocks work

    @patch("leaf.modules.input_modules.file_watcher.Observer.start")
    def test_file_watcher_start_os_error(self, mock_observer_start) -> None:
        # Simulate an OSError with specific errno (e.g., ENOSPC)
        mock_observer_start.side_effect = OSError(errno.ENOSPC, "No space left on device")

        with self.assertRaises(InputError) as context:
            self.file_watcher.start()

        self.assertIn("Inotify watch limit reached", str(context.exception))

    @patch("leaf.modules.input_modules.file_watcher.Observer.start")
    def test_file_watcher_start_unexpected_os_error(self, mock_observer_start) -> None:
        # Simulate an OSError with an unexpected errno code
        mock_observer_start.side_effect = OSError("Unexpected OS error")
        with self.assertRaises(InputError) as context:
            self.file_watcher.start()
        self.assertIn("Unexpected OS error", str(context.exception))

    @patch("builtins.open", new_callable=mock_open)
    def test_file_watcher_on_created_os_error(self, mock_open_file) -> None:
        # Simulate an OSError during file opening on creation
        # Without error_holder, the exception should be raised
        mock_open_file.side_effect = OSError("Failed to open file on creation")
        mock_event = MagicMock()
        mock_event.src_path = self.file_path
        mock_event.is_directory = False
        with self.assertRaises(InputError) as context:
            self.file_watcher.on_created(mock_event)
        self.assertIn("I/O error during creation event", str(context.exception))

    @patch("builtins.open")
    def test_csv_watcher_on_created_parse_error(self, mock_open_file) -> None:
        # Setup Watcher and simulate csv.Error during file reading
        directory = os.path.dirname(self.file_path)
        filename = os.path.basename(self.file_path)
        csv_watcher = FileWatcher(directory, metadata_manager=self.metadata_manager, filenames=filename)
        mock_open_file.side_effect = csv_error("CSV parsing failed")
        mock_event = MagicMock()
        mock_event.src_path = self.file_path
        mock_event.is_directory = False
        with self.assertRaises(InputError) as context:
            csv_watcher.on_created(mock_event)
        self.assertIn("CSV parsing failed", str(context.exception))

    @patch("builtins.open", new_callable=mock_open)
    def test_file_watcher_on_modified_not_found(self, mock_open_file) -> None:
        # Simulate a FileNotFoundError during file opening on modification
        # Without error_holder, the exception should be raised
        mock_open_file.side_effect = FileNotFoundError("File not found on modification")
        mock_event = MagicMock()
        mock_event.src_path = self.file_path
        mock_event.is_directory = False
        with self.assertRaises(InputError) as context:
            self.file_watcher.on_modified(mock_event)
        self.assertIn("File not found during modification event", str(context.exception))

    @patch("builtins.open", new_callable=mock_open)
    def test_file_watcher_on_modified_os_error(self, mock_open_file) -> None:
        # Simulate an OSError during file modification
        # Without error_holder, the exception should be raised
        mock_open_file.side_effect = OSError("OS error during modification")
        mock_event = MagicMock()
        mock_event.src_path = self.file_path
        mock_event.is_directory = False
        with self.assertRaises(InputError) as context:
            self.file_watcher.on_modified(mock_event)
        self.assertIn("I/O error during modification event", str(context.exception))

    @patch.object(FileWatcher, "_handle_exception")
    def test_file_not_found_error(self, mock_handle_exception) -> None:
        error = FileNotFoundError("File not found")
        self.file_watcher._file_event_exception(error, "creation")

        mock_handle_exception.assert_called_once()
        args = mock_handle_exception.call_args[0][0]
        self.assertIsInstance(args, InputError)
        self.assertIn("File not found during creation event", str(args))

    @patch.object(FileWatcher, "_handle_exception")
    def test_permission_error(self, mock_handle_exception) -> None:
        error = PermissionError("Permission denied")
        self.file_watcher._file_event_exception(error, "modification")

        mock_handle_exception.assert_called_once()
        args = mock_handle_exception.call_args[0][0]
        self.assertIsInstance(args, InputError)
        self.assertIn("Permission denied when accessing file during modification event", str(args))

    @patch.object(FileWatcher, "_handle_exception")
    def test_io_error(self, mock_handle_exception) -> None:
        error = OSError("I/O error occurred")
        self.file_watcher._file_event_exception(error, "deletion")

        mock_handle_exception.assert_called_once()
        args = mock_handle_exception.call_args[0][0]
        self.assertIsInstance(args, InputError)
        self.assertIn("I/O error during deletion event", str(args))

    @patch.object(FileWatcher, "_handle_exception")
    def test_unicode_decode_error(self, mock_handle_exception) -> None:
        error = UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")
        self.file_watcher._file_event_exception(error, "creation")

        mock_handle_exception.assert_called_once()
        args = mock_handle_exception.call_args[0][0]
        self.assertIsInstance(args, InputError)
        self.assertIn("Encoding error while reading file", str(args))

    @patch.object(FileWatcher, "_handle_exception")
    def test_generic_error(self, mock_handle_exception) -> None:
        error = Exception("Generic error")
        self.file_watcher._file_event_exception(error, "modification")

        mock_handle_exception.assert_called_once()
        args = mock_handle_exception.call_args[0][0]
        self.assertIsInstance(args, InputError)
        self.assertIn("Error during modification event", str(args))

    def test_event_watcher_hardware_stalled(self) -> None:
        """
        When the FileWatcher cant monitor a file.
        """
        pass

    def test_measurement_adapter_outlier(self) -> None:
        """
        When the FileWatcher cant monitor a file.
        """
        pass

    def test_ensure_all_errors_handled_start(self):
        write_dir = Path(os.path.dirname(os.path.realpath(__file__))) / ".." / "testing_data" / str(uuid.uuid4())
        error_holder = ErrorHolder()
        if not os.path.isdir(write_dir):
            os.makedirs(write_dir, exist_ok=False)
        write_file = os.path.join(write_dir, "tmp1.csv")
        output = MQTT(
            broker,
            port,
            username=un,
            password=pw,
            clientid=None,
            error_holder=error_holder,
        )
        instance_id = f"{uuid.uuid4()}"
        institute = f"{uuid.uuid4()}"
        ins = [
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": instance_id,
                        "institute": institute,
                    },
                    "requirements": {"write_file": write_file},
                }
            }
        ]
        discover_from_config({"EQUIPMENT_INSTANCES": ins}, mock_functional_adapter_path)

        def _start() -> Thread:
            mthread = Thread(target=run_adapters, args=[ins.copy(), output, error_holder])
            mthread.daemon = True
            mthread.start()
            return mthread

        def _stop(thread: Thread) -> None:
            stop_all_adapters()
            time.sleep(10)

        mock_client = MockBioreactorClient(broker, port, username=un, password=pw)

        mock_client.subscribe(f"{institute}/#")
        time.sleep(0.5)
        adapter_thread = _start()
        time.sleep(10)
        excp = InterpreterError("test1_critical", severity=SeverityLevel.CRITICAL)
        error_holder.add_error(excp)

        excp2 = InterpreterError("test2_critical")
        error_holder.add_error(excp2)

        time.sleep(5)
        _stop(adapter_thread)

        expected_exceptions = [excp.to_json(), excp2.to_json()]

        error_messages = None
        for mt in mock_client.messages.keys():
            if "error" in mt and institute in mt:
                error_messages = mock_client.messages[mt]
        for e in expected_exceptions:
            self.assertIn(e, error_messages)


def _is_error_seen(exception, error_holder: ErrorHolder) -> bool:
    for error in error_holder._errors:
        if exception == error["error"]:
            True
    return False
