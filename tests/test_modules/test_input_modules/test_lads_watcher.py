"""Tests for the OPC UA LADS watcher."""

import threading
import unittest
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.lads_watcher import (
    FIRST_RECONNECT_DELAY,
    KEEPALIVE_INTERVAL,
    MAX_RECONNECT_DELAY,
    OPCUA_AVAILABLE,
    RECONNECT_RATE,
    LADSWatcher,
    ua,
)
from leaf.register.metadata import MetadataManager


def make_node(browse_name, node_class, nodeid, children=None, value=None):
    """Build a Mock standing in for an opcua.Node."""
    node = Mock()
    node.get_browse_name.return_value = Mock(Name=browse_name)
    node.get_node_class.return_value = node_class
    node.nodeid = Mock()
    node.nodeid.to_string.return_value = nodeid
    node.nodeid.Identifier = nodeid
    node.get_children.return_value = children or []
    if value is not None:
        node.get_value.return_value = value
    return node


@unittest.skipUnless(OPCUA_AVAILABLE, "OPC UA library not available")
class TestLADSWatcher(unittest.TestCase):
    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.error_holder = ErrorHolder("lads_test")

    def test_lads_watcher_creation(self):
        """Test that LADSWatcher can be created with proper parameters."""
        watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
            functional_units={"pHMeterUnit"},
            exclude_variables=["RawValue"],
            interval=1,
            error_holder=self.error_holder,
        )

        self.assertEqual(watcher._host, "localhost")
        self.assertEqual(watcher._port, 4841)
        self.assertEqual(watcher._functional_units, {"pHMeterUnit"})
        self.assertEqual(watcher._exclude_variables, ["RawValue"])
        self.assertEqual(watcher._interval, 1)

    def test_lads_watcher_creation_defaults(self):
        """functional_units defaults to None (monitor all) and exclude_variables to []."""
        watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
        )

        self.assertIsNone(watcher._functional_units)
        self.assertEqual(watcher._exclude_variables, [])

    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_lads_watcher_start_unavailable(self, mock_client):
        """Test LADSWatcher start when OPC UA is unavailable."""
        with patch("leaf.modules.input_modules.lads_watcher.OPCUA_AVAILABLE", False):
            watcher = LADSWatcher(
                metadata_manager=self.metadata_manager,
                host="localhost",
                port=4841,
                error_holder=self.error_holder,
            )

            with self.assertRaises(Exception) as context:
                watcher.start()

            self.assertIn("OPC UA library is not available", str(context.exception))

    def test_watcher_callback_mechanism(self):
        """Test that watcher can trigger callbacks properly."""
        callback_called = []

        def test_callback(topic, data):
            callback_called.append(data)

        watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
            callbacks=[test_callback],
            error_holder=self.error_holder,
        )

        test_data = {
            "functional_unit": "pHMeterUnit",
            "node": "SensorValue",
            "value": 7.0,
            "timestamp": datetime.now(UTC),
            "data": Mock(),
        }
        watcher._dispatch_callback("measurement", test_data)

        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0], test_data)

    def test_datachange_notification_includes_functional_unit(self):
        """datachange_notification should attach the functional unit for a known variable."""
        callback_called = []
        watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
            callbacks=[lambda topic, data: callback_called.append(data)],
            error_holder=self.error_holder,
        )
        node = make_node("SensorValue", ua.NodeClass.Variable, "ns=7;i=6113")
        watcher._variables = {
            "ns=7;i=6113": {"functional_unit": "pHMeterUnit", "browse_name": "SensorValue", "node": node}
        }

        data = Mock()
        data.monitored_item.Value.SourceTimestamp = datetime.now(UTC)
        watcher.datachange_notification(node, 7.0, data)

        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0]["functional_unit"], "pHMeterUnit")
        self.assertEqual(callback_called[0]["value"], 7.0)


@unittest.skipUnless(OPCUA_AVAILABLE, "OPC UA library not available")
class TestLADSWatcherDiscovery(unittest.TestCase):
    """Tests for LADS structure discovery (DeviceSet -> FunctionalUnitSet -> FunctionSet)."""

    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
        )

    def test_browse_device_set_filters_non_device_objects(self):
        """Only Objects with a FunctionalUnitSet child count as devices (e.g. DeviceFeatures is not a device)."""
        fu_set = make_node("FunctionalUnitSet", ua.NodeClass.Object, "ns=2;i=2")
        device = make_node("pHMeter", ua.NodeClass.Object, "ns=2;i=3", children=[fu_set])
        device_features = make_node("DeviceFeatures", ua.NodeClass.Object, "ns=2;i=4", children=[])
        device_set = make_node("DeviceSet", ua.NodeClass.Object, "ns=2;i=1", children=[device_features, device])
        objects = make_node("Objects", ua.NodeClass.Object, "ns=0;i=85", children=[device_set])

        devices = self.watcher._browse_device_set(objects)

        self.assertEqual(devices, [device])

    def test_browse_functional_units(self):
        fu = make_node("pHMeterUnit", ua.NodeClass.Object, "ns=7;i=5010")
        fu_set = make_node("FunctionalUnitSet", ua.NodeClass.Object, "ns=7;i=5009", children=[fu])
        device = make_node("pHMeter", ua.NodeClass.Object, "ns=7;i=5006", children=[fu_set])

        units = self.watcher._browse_functional_units(device)

        self.assertEqual(units, {"pHMeterUnit": fu})

    def test_walk_variables_dedup_across_duplicate_references(self):
        """LADS nodesets reference the same node via multiple reference types; recursion must not double-count it."""
        sensor_value = make_node("SensorValue", ua.NodeClass.Variable, "ns=7;i=6113", value=6.0)
        # The same node object appears twice, simulating duplicate Organizes/HasComponent references.
        function_set = make_node(
            "FunctionSet", ua.NodeClass.Object, "ns=7;i=5013", children=[sensor_value, sensor_value]
        )

        visited: set[str] = set()
        found: dict = {}
        self.watcher._walk_variables(function_set, visited, found)

        self.assertEqual(len(found), 1)
        self.assertIn("ns=7;i=6113", found)

    def test_walk_variables_skips_skip_list_subtrees(self):
        """Config/metadata subtrees (e.g. Lock) should not be recursed into."""
        locked = make_node("Locked", ua.NodeClass.Variable, "ns=7;i=6085", value=False)
        lock = make_node("Lock", ua.NodeClass.Object, "ns=7;i=5011", children=[locked])

        visited: set[str] = set()
        found: dict = {}
        self.watcher._walk_variables(lock, visited, found)

        self.assertEqual(found, {})

    def test_walk_variables_respects_exclude_variables(self):
        watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
            exclude_variables=["RawValue"],
        )
        raw_value = make_node("RawValue", ua.NodeClass.Variable, "ns=7;i=6112", value=59.0)
        sensor_value = make_node("SensorValue", ua.NodeClass.Variable, "ns=7;i=6113", value=6.0)
        sensor = make_node("pHSensor", ua.NodeClass.Object, "ns=7;i=5019", children=[raw_value, sensor_value])

        visited: set[str] = set()
        found: dict = {}
        watcher._walk_variables(sensor, visited, found)

        self.assertEqual(list(found.keys()), ["ns=7;i=6113"])

    def test_discover_variables_respects_functional_unit_filter(self):
        watcher = LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
            functional_units={"pHMeterUnit"},
        )

        ph_value = make_node("SensorValue", ua.NodeClass.Variable, "ns=7;i=6113", value=6.0)
        ph_function_set = make_node("FunctionSet", ua.NodeClass.Object, "ns=7;i=5013", children=[ph_value])
        ph_unit = make_node("pHMeterUnit", ua.NodeClass.Object, "ns=7;i=5010", children=[ph_function_set])

        other_value = make_node("SensorValue", ua.NodeClass.Variable, "ns=7;i=9999", value=1.0)
        other_function_set = make_node("FunctionSet", ua.NodeClass.Object, "ns=7;i=9998", children=[other_value])
        other_unit = make_node("OtherUnit", ua.NodeClass.Object, "ns=7;i=9997", children=[other_function_set])

        fu_set = make_node("FunctionalUnitSet", ua.NodeClass.Object, "ns=7;i=5009", children=[ph_unit, other_unit])
        device = make_node("pHMeter", ua.NodeClass.Object, "ns=7;i=5006", children=[fu_set])
        device_set = make_node("DeviceSet", ua.NodeClass.Object, "ns=2;i=1", children=[device])
        objects = make_node("Objects", ua.NodeClass.Object, "ns=0;i=85", children=[device_set])

        variables = watcher._discover_variables(objects)

        self.assertEqual(list(variables.keys()), ["ns=7;i=6113"])
        self.assertEqual(variables["ns=7;i=6113"]["functional_unit"], "pHMeterUnit")


@unittest.skipUnless(OPCUA_AVAILABLE, "OPC UA library not available")
class TestLADSWatcherReconnect(unittest.TestCase):
    """Tests for the automatic reconnection logic in LADSWatcher._connection_loop."""

    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.error_holder = ErrorHolder("lads_reconnect_test")

    def _make_watcher(self):
        return LADSWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4841,
            interval=1,
            error_holder=self.error_holder,
        )

    def _discovered(self):
        node = Mock()
        return {"ns=7;i=6113": {"functional_unit": "pHMeterUnit", "browse_name": "SensorValue", "node": node}}

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_reconnects_after_keepalive_failure(self, mock_client_cls, mock_time):
        """A failed keepalive check should trigger a full reconnection."""
        mock_time.sleep = Mock()
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher()

        keepalive_calls = [0]

        def disconnect_side_effect():
            keepalive_calls[0] += 1
            if keepalive_calls[0] == 1:
                raise ConnectionError("Server disconnected")
            watcher._running = False
            return Mock()

        mock_client.get_root_node.return_value.get_browse_name.side_effect = disconnect_side_effect

        with (
            patch.object(watcher, "_discover_variables", return_value=self._discovered()),
            patch.object(watcher, "_subscribe_to_variables"),
        ):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        self.assertEqual(mock_client_cls.call_count, 2)
        self.assertEqual(mock_client.connect.call_count, 2)

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_initial_connection_failure_retries(self, mock_client_cls, mock_time):
        """A failed initial connection should be retried."""
        sleep_calls = []

        def sleep_side_effect(delay):
            sleep_calls.append(delay)
            if len(sleep_calls) >= 2:
                watcher._running = False

        mock_time.sleep.side_effect = sleep_side_effect

        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        mock_client.connect.side_effect = ConnectionRefusedError("Server unavailable")

        watcher = self._make_watcher()
        with (
            patch.object(watcher, "_discover_variables", return_value=self._discovered()),
            patch.object(watcher, "_subscribe_to_variables"),
        ):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        self.assertGreaterEqual(mock_client.connect.call_count, 2)

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_no_variables_discovered_triggers_reconnect(self, mock_client_cls, mock_time):
        """An empty discovery result should be treated as a connection failure and retried."""
        sleep_calls = []

        def sleep_side_effect(delay):
            sleep_calls.append(delay)
            if len(sleep_calls) >= 2:
                watcher._running = False

        mock_time.sleep.side_effect = sleep_side_effect

        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher()
        with patch.object(watcher, "_discover_variables", return_value={}):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        self.assertGreaterEqual(mock_client.connect.call_count, 2)

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_exponential_backoff_on_connection_failure(self, mock_client_cls, mock_time):
        """Reconnect delay should double with each failed attempt, up to MAX_RECONNECT_DELAY."""
        sleep_calls = []

        def sleep_side_effect(delay):
            sleep_calls.append(delay)
            reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
            if len(reconnect_delays) >= 3:
                watcher._running = False

        mock_time.sleep.side_effect = sleep_side_effect

        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        mock_client.connect.side_effect = ConnectionRefusedError("Server unavailable")

        watcher = self._make_watcher()
        with patch.object(watcher, "_discover_variables", return_value=self._discovered()):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
        self.assertGreaterEqual(len(reconnect_delays), 3)
        self.assertEqual(reconnect_delays[0], FIRST_RECONNECT_DELAY)
        self.assertEqual(reconnect_delays[1], FIRST_RECONNECT_DELAY * RECONNECT_RATE)
        self.assertEqual(reconnect_delays[2], FIRST_RECONNECT_DELAY * RECONNECT_RATE**2)

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_backoff_resets_after_successful_reconnect(self, mock_client_cls, mock_time):
        """After a successful reconnect, the backoff delay should reset to FIRST_RECONNECT_DELAY."""
        sleep_calls = []
        connect_calls = [0]

        mock_time.sleep.side_effect = lambda d: sleep_calls.append(d)

        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        def connect_side_effect():
            connect_calls[0] += 1
            if connect_calls[0] == 1:
                raise ConnectionRefusedError("Server unavailable")

        mock_client.connect.side_effect = connect_side_effect

        keepalive_calls = [0]

        def disconnect_side_effect():
            keepalive_calls[0] += 1
            if keepalive_calls[0] == 1:
                raise ConnectionError("Server disconnected")
            watcher._running = False
            return Mock()

        mock_client.get_root_node.return_value.get_browse_name.side_effect = disconnect_side_effect

        watcher = self._make_watcher()
        with (
            patch.object(watcher, "_discover_variables", return_value=self._discovered()),
            patch.object(watcher, "_subscribe_to_variables"),
        ):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
        self.assertGreaterEqual(len(reconnect_delays), 2)
        self.assertEqual(reconnect_delays[0], FIRST_RECONNECT_DELAY)
        self.assertEqual(reconnect_delays[1], FIRST_RECONNECT_DELAY)

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_cleanup_called_on_keepalive_failure(self, mock_client_cls, mock_time):
        """Client disconnect should be called when a keepalive check fails."""
        mock_time.sleep = Mock()
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher()

        keepalive_calls = [0]

        def disconnect_side_effect():
            keepalive_calls[0] += 1
            if keepalive_calls[0] == 1:
                raise ConnectionError("Server disconnected")
            watcher._running = False
            return Mock()

        mock_client.get_root_node.return_value.get_browse_name.side_effect = disconnect_side_effect

        with (
            patch.object(watcher, "_discover_variables", return_value=self._discovered()),
            patch.object(watcher, "_subscribe_to_variables"),
        ):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        self.assertGreaterEqual(mock_client.disconnect.call_count, 1)

    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_start_twice_does_not_create_second_thread(self, mock_client_cls):
        """Calling start() on an already-running watcher should be a no-op."""
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher()

        hold_open = threading.Event()

        def connect_side_effect():
            hold_open.wait(timeout=3.0)
            watcher._running = False

        mock_client.connect.side_effect = connect_side_effect

        with (
            patch.object(watcher, "_discover_variables", return_value=self._discovered()),
            patch.object(watcher, "_subscribe_to_variables"),
        ):
            watcher.start()
            first_thread = watcher._thread

            watcher.start()

            hold_open.set()
            watcher._thread.join(timeout=5.0)

        self.assertIs(watcher._thread, first_thread)
        self.assertEqual(mock_client_cls.call_count, 1)

    @patch("leaf.modules.input_modules.lads_watcher.time")
    @patch("leaf.modules.input_modules.lads_watcher.Client")
    def test_backoff_caps_at_max_reconnect_delay(self, mock_client_cls, mock_time):
        """Reconnect delay should never exceed MAX_RECONNECT_DELAY."""
        sleep_calls = []
        max_failures = 8

        def sleep_side_effect(delay):
            sleep_calls.append(delay)
            reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
            if len(reconnect_delays) >= max_failures:
                watcher._running = False

        mock_time.sleep.side_effect = sleep_side_effect

        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        mock_client.connect.side_effect = ConnectionRefusedError("Server unavailable")

        watcher = self._make_watcher()
        with patch.object(watcher, "_discover_variables", return_value=self._discovered()):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
        self.assertTrue(all(d <= MAX_RECONNECT_DELAY for d in reconnect_delays))
        self.assertIn(MAX_RECONNECT_DELAY, reconnect_delays)


if __name__ == "__main__":
    unittest.main()
