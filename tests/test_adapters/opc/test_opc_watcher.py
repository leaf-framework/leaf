"""Tests for the OPC UA watcher."""

import logging
import threading
import time
import unittest
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from leafobject import LeafPoint  # pyright: ignore[reportMissingTypeStubs]

from leaf.adapters.core_adapters.discrete_experiment_adapter import DiscreteExperimentAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.opc_watcher import (
    FIRST_RECONNECT_DELAY,
    KEEPALIVE_INTERVAL,
    MAX_RECONNECT_DELAY,
    OPCUA_AVAILABLE,
    RECONNECT_RATE,
    OPCWatcher,
)
from leaf.register.metadata import MetadataManager

metadata_fn = {
    "adapter_id": "MBPOPC",
    "equipment_data": {
        "version": "1.0",
        "manufacturer": "BearTree",
        "device_type": "Bioreactor",
        "application": "OPC Data logger for the BearTree Bioreactor",
    },
    "requirements": {"interval": "int", "host": "str", "port": "int", "topics": ["temperature", "pressure"]},
    "adapter_data": {},
}


class MBPOPCInterpreter(AbstractInterpreter):
    def __init__(self, metadata_manager):
        super().__init__()
        self.metadata_manager = metadata_manager
        self.message_count = 0

    def metadata(self, data):
        metadata = super().metadata(data)
        metadata.update({"device_type": "opc_ua_device", "protocol": "opc_ua"})
        return metadata

    def measurement(self, data):
        if not data or not isinstance(data, dict):
            return False

        self.message_count += 1

        node = data.get("node", "unknown")
        value = data.get("value")
        timestamp = data.get("timestamp")

        if value is None:
            return False

        point = LeafPoint()
        point.set_measurement("opc_ua_device")
        if not timestamp:
            timestamp = datetime.now(UTC)
        point.set_timestamp(timestamp)
        point.set_entity_tag(f"node_{node}")
        point.set_metric("value")
        point.add_field("value", float(value))
        point.add_field("message_count", self.message_count)

        return [point]

    def simulate(self):
        return


class MBPOPCAdapter(DiscreteExperimentAdapter):
    """Test adapter for OPC UA device testing."""

    def __init__(
        self,
        instance_data,
        output,
        topics: set[str] | None = None,
        exclude_topics: list[str] | None = None,
        host: str = "localhost",
        port: int = 4840,
        reporting_interval=10,
        maximum_message_size: int | None = 100,
        error_holder: ErrorHolder | None = None,
        experiment_timeout: int | None = None,
        external_watcher: OPCWatcher | None = None,
    ) -> None:
        if instance_data is None or instance_data == {}:
            raise ValueError("Instance data cannot be empty")
        if topics is None:
            topics = [".*R1.*"]
        if exclude_topics is None:
            exclude_topics = []

        metadata_manager = MetadataManager()
        watcher: OPCWatcher = OPCWatcher(
            metadata_manager=metadata_manager,
            topics=topics,
            port=port,
            host=host,
            exclude_topics=exclude_topics,
            interval=60,
        )

        interpreter = MBPOPCInterpreter(metadata_manager=metadata_manager)

        super().__init__(
            instance_data=instance_data,
            watcher=watcher,
            output=output,
            interpreter=interpreter,
            maximum_message_size=maximum_message_size,
            error_holder=error_holder,
            metadata_manager=metadata_manager,
            experiment_timeout=experiment_timeout,
        )

        self._metadata_manager.add_equipment_data(metadata_fn)


@unittest.skipUnless(OPCUA_AVAILABLE, "OPC UA library not available")
class TestOpcWatcher(unittest.TestCase):
    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.error_holder = ErrorHolder("opc_test")
        self.interpreter = MBPOPCInterpreter(self.metadata_manager)

        # Add metadata
        self.metadata_manager.add_equipment_data(metadata_fn)
        #
        logging.info("OPC UA library is available for testing.")

    def test_opc_watcher_creation(self):
        """Test that OPCWatcher can be created with proper parameters."""
        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4840,
            topics={"temperature", "pressure"},
            exclude_topics=[],
            interval=1,
            error_holder=self.error_holder,
        )

        self.assertEqual(watcher._host, "localhost")
        self.assertEqual(watcher._port, 4840)
        self.assertEqual(watcher._topics, {"temperature", "pressure"})
        self.assertEqual(watcher._exclude_topics, [])
        self.assertEqual(watcher._interval, 1)

    def test_interpreter_processes_opc_data(self):
        """Test that the interpreter processes OPC UA data correctly."""
        # Simulate OPC UA data
        opc_data = {"node": "temperature_sensor_01", "value": 25.5, "timestamp": datetime.now(UTC), "data": Mock()}

        result = self.interpreter.measurement(opc_data)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], LeafPoint)
        self.assertEqual(result[0].measurement, "opc_ua_device")
        self.assertEqual(self.interpreter.message_count, 1)

    def test_invalid_data_handled_gracefully(self):
        """Test graceful handling of invalid data."""
        # Test with None
        result = self.interpreter.measurement(None)
        self.assertFalse(result)

        # Test with empty dict
        result = self.interpreter.measurement({})
        self.assertFalse(result)

        # Test with missing value
        result = self.interpreter.measurement({"node": "test"})
        self.assertFalse(result)

    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_opc_watcher_start_unavailable(self, mock_client):
        """Test OPCWatcher start when OPC UA is unavailable."""
        # Temporarily set OPCUA_AVAILABLE to False
        with patch("leaf.modules.input_modules.opc_watcher.OPCUA_AVAILABLE", False):
            watcher = OPCWatcher(
                metadata_manager=self.metadata_manager,
                host="localhost",
                port=4840,
                topics=set(),
                exclude_topics=[],
                error_holder=self.error_holder,
            )

            with self.assertRaises(Exception) as context:
                watcher.start()

            self.assertIn("OPC UA library is not available", str(context.exception))

    def test_metadata_processing(self):
        """Test metadata processing."""
        test_data = {"test": "data"}
        result = self.interpreter.metadata(test_data)

        self.assertIn("device_type", result)
        self.assertIn("protocol", result)
        self.assertEqual(result["device_type"], "opc_ua_device")
        self.assertEqual(result["protocol"], "opc_ua")

    def test_watcher_callback_mechanism(self):
        """Test that watcher can trigger callbacks properly."""
        callback_called = []

        def test_callback(func, data):
            callback_called.append(data)

        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4840,
            topics={"temperature"},
            exclude_topics=[],
            interval=1,
            callbacks=[test_callback],
            error_holder=self.error_holder,
        )

        # Simulate callback trigger
        test_data = {"node": "temperature_sensor", "value": 23.5, "timestamp": datetime.now(UTC), "data": Mock()}

        # Manually trigger the callback mechanism
        watcher._dispatch_callback(lambda x: x, test_data)

        # Verify callback was triggered
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0], test_data)


class FakeClient:
    """Typed stand-in for opcua.Client that records the credentials it gets."""

    def __init__(self, url: str) -> None:
        self.url: str = url
        self.user: str | None = None
        self.password: str | None = None
        self.security: str | None = None
        self.certificate: str | None = None
        self.private_key: str | None = None

    def set_security_string(self, security: str) -> None:
        self.security = security

    def load_client_certificate(self, path: str) -> None:
        self.certificate = path

    def load_private_key(self, path: str | None) -> None:
        self.private_key = path

    def set_user(self, username: str) -> None:
        self.user = username

    def set_password(self, password: str | None) -> None:
        self.password = password


@unittest.skipUnless(OPCUA_AVAILABLE, "OPC UA library not available")
class TestOPCWatcherReconnect(unittest.TestCase):
    """Tests for the automatic reconnection logic in OPCWatcher._connection_loop."""

    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.error_holder = ErrorHolder("opc_reconnect_test")
        self.metadata_manager.add_equipment_data(metadata_fn)

    def _make_watcher(self, topics: set[str] | None = None, wait: Mock | None = None) -> OPCWatcher:
        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4840,
            topics=topics or {"temperature"},
            exclude_topics=[],
            interval=1,
            error_holder=self.error_holder,
        )
        if wait is not None:
            # Drive the loop's keepalive/backoff waits from the test instead of real time.
            watcher._stop_event.wait = wait
        return watcher

    @patch("leaf.modules.input_modules.opc_watcher.time")
    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_reconnects_after_keepalive_failure(self, mock_client_cls, mock_time):
        """A failed keepalive check should trigger a full reconnection."""
        mock_time.sleep = Mock()
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher(wait=mock_time.sleep)

        keepalive_calls = [0]

        def disconnect_side_effect():
            keepalive_calls[0] += 1
            if keepalive_calls[0] == 1:
                raise ConnectionError("Server disconnected")
            # Second keepalive succeeds — stop the watcher so the thread exits
            watcher._running = False
            return Mock()

        mock_client.get_root_node.return_value.get_browse_name.side_effect = disconnect_side_effect

        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        # Client should have been constructed twice: initial connect + one reconnect
        self.assertEqual(mock_client_cls.call_count, 2)
        self.assertEqual(mock_client.connect.call_count, 2)

    @patch("leaf.modules.input_modules.opc_watcher.Client", FakeClient)
    def test_credentials_set_on_client(self) -> None:
        """A configured username and password are set on every new client."""
        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4840,
            topics={"temperature"},
            exclude_topics=[],
            username="leaf",
            password="secret",
        )
        client = watcher._new_client()

        assert isinstance(client, FakeClient)
        self.assertEqual(client.user, "leaf")
        self.assertEqual(client.password, "secret")

    @patch("leaf.modules.input_modules.opc_watcher.Client", FakeClient)
    def test_anonymous_by_default(self) -> None:
        """Without a username the client connects anonymously."""
        client = self._make_watcher()._new_client()

        assert isinstance(client, FakeClient)
        self.assertIsNone(client.user)
        self.assertIsNone(client.password)
        self.assertIsNone(client.security)
        self.assertIsNone(client.certificate)

    @patch("leaf.modules.input_modules.opc_watcher.Client", FakeClient)
    def test_security_and_certificate_set_on_client(self) -> None:
        """A security string and login certificate are passed to every new client."""
        watcher = OPCWatcher(
            metadata_manager=self.metadata_manager,
            host="localhost",
            port=4840,
            topics={"temperature"},
            exclude_topics=[],
            security="Basic256Sha256,SignAndEncrypt,c.pem,k.pem",
            certificate="user.pem",
            private_key="user_key.pem",
        )
        client = watcher._new_client()

        assert isinstance(client, FakeClient)
        self.assertEqual(client.security, "Basic256Sha256,SignAndEncrypt,c.pem,k.pem")
        self.assertEqual(client.certificate, "user.pem")
        self.assertEqual(client.private_key, "user_key.pem")

    @patch("leaf.modules.input_modules.opc_watcher.time")
    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_initial_connection_failure_retries(self, mock_client_cls, mock_time):
        """A failed initial connection should be retried."""
        connect_calls = [0]
        sleep_calls = []

        def sleep_side_effect(delay):
            sleep_calls.append(delay)
            # Stop after two reconnect-delay sleeps so the thread exits
            if len(sleep_calls) >= 2:
                watcher._running = False

        mock_time.sleep.side_effect = sleep_side_effect

        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        def connect_side_effect():
            connect_calls[0] += 1
            raise ConnectionRefusedError("Server unavailable")

        mock_client.connect.side_effect = connect_side_effect

        watcher = self._make_watcher(wait=mock_time.sleep)
        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        self.assertGreaterEqual(mock_client.connect.call_count, 2)

    @patch("leaf.modules.input_modules.opc_watcher.time")
    @patch("leaf.modules.input_modules.opc_watcher.Client")
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

        watcher = self._make_watcher(wait=mock_time.sleep)
        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
        self.assertGreaterEqual(len(reconnect_delays), 3)
        self.assertEqual(reconnect_delays[0], FIRST_RECONNECT_DELAY)
        self.assertEqual(reconnect_delays[1], FIRST_RECONNECT_DELAY * RECONNECT_RATE)
        self.assertEqual(reconnect_delays[2], FIRST_RECONNECT_DELAY * RECONNECT_RATE**2)

    @patch("leaf.modules.input_modules.opc_watcher.time")
    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_backoff_resets_after_successful_reconnect(self, mock_client_cls, mock_time):
        """After a successful reconnect, the backoff delay should reset to FIRST_RECONNECT_DELAY."""
        sleep_calls = []
        connect_calls = [0]

        mock_time.sleep.side_effect = lambda d: sleep_calls.append(d)

        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        # First connect fails → backoff increments. Subsequent connects succeed.
        def connect_side_effect():
            connect_calls[0] += 1
            if connect_calls[0] == 1:
                raise ConnectionRefusedError("Server unavailable")

        mock_client.connect.side_effect = connect_side_effect

        keepalive_calls = [0]

        def disconnect_side_effect():
            keepalive_calls[0] += 1
            if keepalive_calls[0] == 1:
                # First keepalive after reconnect fails → triggers another reconnect
                raise ConnectionError("Server disconnected")
            # Second keepalive: stop the watcher
            watcher._running = False
            return Mock()

        mock_client.get_root_node.return_value.get_browse_name.side_effect = disconnect_side_effect

        watcher = self._make_watcher(wait=mock_time.sleep)
        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        # sleep() call sequence:
        #   sleep(1)  → reconnect wait after first connect failure (delay was 1, then doubles to 2)
        #   sleep(10) → keepalive after successful reconnect
        #   sleep(1)  → reconnect wait after keepalive failure (delay reset to 1)
        #   sleep(10) → keepalive on third connect (watcher stops here)
        reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
        self.assertGreaterEqual(len(reconnect_delays), 2)
        self.assertEqual(reconnect_delays[0], FIRST_RECONNECT_DELAY)  # first failure delay
        self.assertEqual(reconnect_delays[1], FIRST_RECONNECT_DELAY)  # reset after successful connect

    @patch("leaf.modules.input_modules.opc_watcher.time")
    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_cleanup_called_on_keepalive_failure(self, mock_client_cls, mock_time):
        """Client disconnect should be called when a keepalive check fails."""
        mock_time.sleep = Mock()
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher(wait=mock_time.sleep)

        keepalive_calls = [0]

        def disconnect_side_effect():
            keepalive_calls[0] += 1
            if keepalive_calls[0] == 1:
                raise ConnectionError("Server disconnected")
            watcher._running = False
            return Mock()

        mock_client.get_root_node.return_value.get_browse_name.side_effect = disconnect_side_effect

        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        # disconnect() should be called at least once (once per cleanup cycle)
        self.assertGreaterEqual(mock_client.disconnect.call_count, 1)

    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_start_twice_does_not_create_second_thread(self, mock_client_cls):
        """Calling start() on an already-running watcher should be a no-op."""
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        watcher = self._make_watcher()

        # Use an event to hold the connection loop open long enough to call start() twice
        hold_open = threading.Event()

        def connect_side_effect():
            hold_open.wait(timeout=3.0)
            watcher._running = False

        mock_client.connect.side_effect = connect_side_effect

        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            first_thread = watcher._thread

            # Call start() again while the thread is still alive
            watcher.start()

            hold_open.set()
            watcher._thread.join(timeout=5.0)

        # The second start() should have been a no-op — same thread, one Client instance
        self.assertIs(watcher._thread, first_thread)
        self.assertEqual(mock_client_cls.call_count, 1)

    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_stop_interrupts_keepalive_wait(self, mock_client_cls: Mock) -> None:
        """stop() wakes the thread from its 10 s keepalive wait instead of timing out."""
        connected = threading.Event()
        mock_client_cls.return_value.connect.side_effect = lambda: connected.set()
        watcher = self._make_watcher()

        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            self.assertTrue(connected.wait(timeout=2.0))
            started = time.monotonic()
            watcher.stop()

        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(watcher.is_running())

    @patch("leaf.modules.input_modules.opc_watcher.time")
    @patch("leaf.modules.input_modules.opc_watcher.Client")
    def test_backoff_caps_at_max_reconnect_delay(self, mock_client_cls, mock_time):
        """Reconnect delay should never exceed MAX_RECONNECT_DELAY."""
        sleep_calls = []
        # Need enough failures to saturate the cap: 1→2→4→8→16→32→60 (7 failures)
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

        watcher = self._make_watcher(wait=mock_time.sleep)
        with patch.object(watcher, "_subscribe_to_topics"):
            watcher.start()
            watcher._thread.join(timeout=5.0)

        reconnect_delays = [d for d in sleep_calls if d != KEEPALIVE_INTERVAL]
        self.assertTrue(all(d <= MAX_RECONNECT_DELAY for d in reconnect_delays))
        # After enough failures the delay must have reached the cap
        self.assertIn(MAX_RECONNECT_DELAY, reconnect_delays)


if __name__ == "__main__":
    unittest.main()
