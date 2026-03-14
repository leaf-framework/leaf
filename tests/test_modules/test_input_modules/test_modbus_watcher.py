import logging
import os
import socket
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.modbus_watcher import ModbusWatcher
from leaf.register.metadata import MetadataManager

# Read test_modbus_config.yaml
with open(f"{os.path.dirname(__file__)}/test_modbus_config.yaml", "r") as stream:
    CONFIG = yaml.safe_load(stream)
    MODBUS_CONFIG = CONFIG["EQUIPMENT_INSTANCES"][0]['equipment']['requirements']
    logging.info(MODBUS_CONFIG)
    print(MODBUS_CONFIG)


def make_register_result(values: list[int]) -> MagicMock:
    result = MagicMock()
    result.isError.return_value = False
    result.registers = values
    return result


def make_error_result() -> MagicMock:
    result = MagicMock()
    result.isError.return_value = True
    return result


class TestModbusWatcherInit(unittest.TestCase):
    def test_stores_config_values(self):
        watcher = ModbusWatcher(**MODBUS_CONFIG)
        self.assertEqual(watcher._host, "192.168.1.12")
        self.assertEqual(watcher._port, 502)
        self.assertEqual(watcher._device_id, 1)
        self.assertEqual(watcher._interval, 5)
        self.assertEqual(len(watcher._registers), 4)

    def test_default_port_and_device_id(self):
        watcher = ModbusWatcher(host="10.0.0.1", interval=10, registers=[])
        self.assertEqual(watcher._port, 502)
        self.assertEqual(watcher._device_id, 1)

    def test_not_running_on_init(self):
        watcher = ModbusWatcher(**MODBUS_CONFIG)
        self.assertFalse(watcher.is_running())


class TestModbusWatcherReadRegisters(unittest.TestCase):
    """Unit tests for _read_registers without starting the poll thread."""

    def setUp(self):
        self.watcher = ModbusWatcher(**MODBUS_CONFIG)
        self.mock_client = MagicMock()
        self.watcher._client = self.mock_client

    def _setup_responses(self, temp_raw=2350, humidity_raw=4512, presence_raw=1, last_ir_regs=None):
        last_ir_regs = last_ir_regs or [0x0001, 0x8A6B]

        def side_effect(address, count, device_id):
            if address == 40301 - 40001:
                return make_register_result([temp_raw])
            if address == 40317 - 40001:
                return make_register_result([humidity_raw])
            if address == 40803 - 40001:
                return make_register_result([presence_raw])
            if address == 42002 - 40001:
                return make_register_result(last_ir_regs)
            return make_error_result()

        self.mock_client.read_holding_registers.side_effect = side_effect

    def test_scale_applied_to_temperature(self):
        self._setup_responses(temp_raw=2350)
        data = self.watcher._read_registers()
        self.assertAlmostEqual(data["temperature"], 23.50)

    def test_scale_applied_to_humidity(self):
        self._setup_responses(humidity_raw=4512)
        data = self.watcher._read_registers()
        self.assertAlmostEqual(data["humidity"], 45.12)

    def test_default_scale_for_presence(self):
        self._setup_responses(presence_raw=1)
        data = self.watcher._read_registers()
        self.assertEqual(data["presence"], 1.0)

    def test_multi_register_returns_list(self):
        self._setup_responses(last_ir_regs=[0x0001, 0x8A6B])
        data = self.watcher._read_registers()
        self.assertIsInstance(data["last_ir_ts"], list)
        self.assertEqual(len(data["last_ir_ts"]), 2)

    def test_register_address_offset(self):
        """Addresses are passed to pymodbus with the 40001 offset stripped."""
        self._setup_responses()
        self.watcher._read_registers()
        calls = {call.kwargs["address"] for call in self.mock_client.read_holding_registers.call_args_list}
        self.assertIn(40301 - 40001, calls)
        self.assertIn(40317 - 40001, calls)

    def test_error_register_skipped(self):
        """A Modbus error on one register should not prevent others from being read."""
        self.mock_client.read_holding_registers.side_effect = None

        def side_effect(address, count, device_id):
            if address == 40301 - 40001:
                return make_error_result()
            return make_register_result([100])

        self.mock_client.read_holding_registers.side_effect = side_effect
        data = self.watcher._read_registers()
        self.assertNotIn("temperature", data)
        self.assertIn("humidity", data)

    def test_register_missing_name_skipped(self):
        watcher = ModbusWatcher(
            host="192.168.1.12",
            interval=5,
            registers=[{"address": 40301, "scale": 0.01}],  # no name
        )
        watcher._client = self.mock_client
        data = watcher._read_registers()
        self.assertEqual(data, {})

    def test_register_missing_address_skipped(self):
        watcher = ModbusWatcher(
            host="192.168.1.12",
            interval=5,
            registers=[{"name": "temperature", "scale": 0.01}],  # no address
        )
        watcher._client = self.mock_client
        data = watcher._read_registers()
        self.assertEqual(data, {})


class TestModbusWatcherEmit(unittest.TestCase):
    def test_emit_uses_metadata_manager_topic(self):
        metadata_manager = MetadataManager()
        received = []

        def callback(topic, data):
            received.append((topic, data))

        watcher = ModbusWatcher(metadata_manager=metadata_manager, callbacks=[callback], **MODBUS_CONFIG)
        watcher._emit({"temperature": 23.5})

        self.assertEqual(len(received), 1)
        topic, data = received[0]
        # topic is a callable wrapper; compare the generated string to the expected one
        self.assertEqual(topic(), metadata_manager.experiment.measurement())
        self.assertEqual(data["temperature"], 23.5)

    def test_emit_without_metadata_manager_falls_back_to_string(self):
        received = []

        def callback(topic, data):
            received.append((topic, data))

        watcher = ModbusWatcher(callbacks=[callback], **MODBUS_CONFIG)
        watcher._emit({"presence": 1.0})

        self.assertEqual(len(received), 1)
        topic, data = received[0]
        self.assertEqual(topic, "measurement")
        self.assertEqual(data["presence"], 1.0)


class TestModbusWatcherStartStop(unittest.TestCase):
    @patch("leaf.modules.input_modules.modbus_watcher.MODBUS_AVAILABLE", True)
    @patch("leaf.modules.input_modules.modbus_watcher.ModbusTcpClient")
    def test_start_connects_and_sets_running(self, mock_cls):
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_cls.return_value = mock_client

        watcher = ModbusWatcher(**MODBUS_CONFIG)
        watcher.start()

        self.assertTrue(watcher.is_running())
        mock_client.connect.assert_called_once()

        watcher.stop()

    @patch("leaf.modules.input_modules.modbus_watcher.MODBUS_AVAILABLE", True)
    @patch("leaf.modules.input_modules.modbus_watcher.ModbusTcpClient")
    def test_stop_closes_client_and_clears_running(self, mock_cls):
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_cls.return_value = mock_client

        watcher = ModbusWatcher(**MODBUS_CONFIG)
        watcher.start()
        watcher.stop()

        self.assertFalse(watcher.is_running())
        mock_client.close.assert_called_once()
        self.assertIsNone(watcher._client)

    @patch("leaf.modules.input_modules.modbus_watcher.MODBUS_AVAILABLE", True)
    @patch("leaf.modules.input_modules.modbus_watcher.ModbusTcpClient")
    def test_connection_failure_raises(self, mock_cls):
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        mock_cls.return_value = mock_client

        watcher = ModbusWatcher(**MODBUS_CONFIG)
        with self.assertRaises(ConnectionError):
            watcher.start()

    @patch("leaf.modules.input_modules.modbus_watcher.MODBUS_AVAILABLE", True)
    @patch("leaf.modules.input_modules.modbus_watcher.ModbusTcpClient")
    def test_poll_dispatches_callback(self, mock_cls):
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.read_holding_registers.return_value = make_register_result([2350])
        mock_cls.return_value = mock_client

        received = []

        def callback(topic, data):
            received.append((topic, data))

        watcher = ModbusWatcher(
            host="192.168.1.12",
            interval=1,
            registers=[{"name": "temperature", "address": 40301, "scale": 0.01}],
            callbacks=[callback],
        )
        watcher.start()
        time.sleep(1.5)  # let at least one poll fire
        watcher.stop()

        self.assertTrue(len(received) >= 1)
        _, data = received[0]
        logging.info(f"Received data: {data}")
        self.assertAlmostEqual(data["temperature"], 23.50)


def _device_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


_HOST = MODBUS_CONFIG["host"]
_PORT = MODBUS_CONFIG["port"]
DEVICE_REACHABLE = _device_reachable(_HOST, _PORT)


from leaf.modules.input_modules.modbus_watcher import MODBUS_AVAILABLE

@unittest.skipUnless(MODBUS_AVAILABLE, "pymodbus not installed")
@unittest.skipUnless(DEVICE_REACHABLE, f"Modbus device not reachable at {_HOST}:{_PORT}")
class TestModbusWatcherIntegration(unittest.TestCase):
    """Integration tests — only run when the physical device is reachable."""

    def setUp(self):
        self.watcher = ModbusWatcher(**MODBUS_CONFIG)

    def tearDown(self):
        if self.watcher.is_running():
            self.watcher.stop()

    def test_connects_and_starts(self):
        self.watcher.start()
        self.assertTrue(self.watcher.is_running())

    def test_reads_all_registers(self):
        self.watcher.start()
        data = self.watcher._read_registers()
        self.assertIn("temperature", data)
        self.assertIn("humidity", data)
        self.assertIn("presence", data)
        self.assertIn("last_ir_ts", data)

    def test_temperature_in_plausible_range(self):
        self.watcher.start()
        data = self.watcher._read_registers()
        temp = data["temperature"]
        self.assertGreater(temp, -10.0)
        self.assertLess(temp, 60.0)

    def test_humidity_in_plausible_range(self):
        self.watcher.start()
        data = self.watcher._read_registers()
        humidity = data["humidity"]
        self.assertGreaterEqual(humidity, 0.0)
        self.assertLessEqual(humidity, 100.0)

    def test_poll_fires_callback(self):
        received = []

        def callback(topic, data):
            received.append(data)

        self.watcher.add_callback(callback)
        self.watcher._metadata_manager = None  # use plain "measurement" topic
        self.watcher.start()
        time.sleep(MODBUS_CONFIG["interval"] + 1)
        self.watcher.stop()

        self.assertGreaterEqual(len(received), 1)
        logging.info(f"Integration poll data: {received[0]}")


if __name__ == "__main__":
    unittest.main()
