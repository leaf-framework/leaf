import os
import random
import socket
import sys
import threading
import time
import unittest

import pytest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.opc_watcher import OPCWatcher
from leaf.register.metadata import MetadataManager

# Import OPC UA library
try:
    from opcua import Server

    OPCUA_AVAILABLE = True
except ImportError:
    OPCUA_AVAILABLE = False
    Server = None


# opcua's Server() builds a ~37k-line standard address space, which can pass the 30s default on a busy CI runner.
pytestmark = pytest.mark.timeout(120)


def free_port() -> int:
    """Ask the OS for a free port, so parallel test workers never share one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(condition, timeout=10.0):
    """Poll until condition() is true or the timeout passes; returns the last result."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


class OPCDemoServer:
    """Demo OPC UA Server for testing"""

    def __init__(self, host="0.0.0.0", port=4840, users=None):
        if not OPCUA_AVAILABLE:
            raise ImportError("OPC UA library not available")

        self.host = host
        self.port = port
        self.server = Server()
        self.server.set_endpoint(f"opc.tcp://{host}:{port}/freeopcua/server/")
        self.server.set_server_name("Leaf OPC UA Test Server")
        if users:
            # Only username logins; anonymous clients are rejected.
            self.server.set_security_IDs(["Username"])
            user_manager = self.server.user_manager
            assert user_manager is not None
            user_manager.set_user_manager(lambda _session, user, pwd: users.get(user) == pwd)

        # Setup namespace
        self.uri = "http://leaf.test.opcua"
        self.idx = self.server.register_namespace(self.uri)

        # Variables to store node references
        self.temperature_node = None
        self.pressure_node = None
        self.status_node = None
        self.counter_node = None

        self._running = False
        self._update_thread = None

    def setup_nodes(self):
        """Setup demo nodes"""
        from opcua import ua

        objects = self.server.get_objects_node()

        # Add a demo object
        demo_object = objects.add_object(self.idx, "DemoDevice")

        # Add variables with explicit string NodeIds
        self.temperature_node = demo_object.add_variable(ua.NodeId("Temperature", self.idx), "Temperature", 20.0)
        self.pressure_node = demo_object.add_variable(ua.NodeId("Pressure", self.idx), "Pressure", 101.3)
        self.status_node = demo_object.add_variable(ua.NodeId("Status", self.idx), "Status", "Running")
        self.counter_node = demo_object.add_variable(ua.NodeId("Counter", self.idx), "Counter", 0)

        # Make variables writable
        self.temperature_node.set_writable()
        self.pressure_node.set_writable()
        self.status_node.set_writable()
        self.counter_node.set_writable()

    def start(self):
        """Start the OPC UA server"""
        self.setup_nodes()
        self.server.start()
        self._running = True

    def stop(self):
        """Stop the OPC UA server"""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=2)
        self.server.stop()

    def update_values_once(self):
        """Update values once (for testing)"""
        if self.temperature_node:
            temp = 20.0 + random.uniform(-2, 2)
            self.temperature_node.set_value(temp)

        if self.pressure_node:
            pressure = 101.3 + random.uniform(-0.5, 0.5)
            self.pressure_node.set_value(pressure)

        if self.counter_node:
            current = self.counter_node.get_value()
            self.counter_node.set_value(current + 1)

    def start_updating_values(self, interval=1):
        """Start continuously updating values in a background thread"""

        def update_loop():
            count = 0
            while self._running:
                count += 1
                self.update_values_once()
                time.sleep(interval)

        self._update_thread = threading.Thread(target=update_loop, daemon=True)
        self._update_thread.start()


@unittest.skipIf(not OPCUA_AVAILABLE, "OPC UA library not available")
class TestOPCWatcher(unittest.TestCase):
    """Test OPCWatcher with embedded demo server"""

    @classmethod
    def setUpClass(cls):
        """Start OPC demo server once for all tests"""
        cls.demo_server = None
        cls.server_failed = False
        try:
            cls.port = free_port()
            cls.demo_server = OPCDemoServer(host="127.0.0.1", port=cls.port)
            cls.demo_server.start()
        except Exception as e:
            cls.server_failed = True
            cls.server_error = str(e)
            print(f"Failed to start OPC demo server: {e}")

    @classmethod
    def tearDownClass(cls):
        """Stop OPC demo server"""
        if cls.demo_server:
            try:
                cls.demo_server.stop()
            except Exception as e:
                print(f"Error stopping OPC demo server: {e}")

    def test_opc_watcher_connection(self):
        """Test that OPCWatcher can successfully connect to the demo server"""
        if self.server_failed:
            self.skipTest(f"OPC demo server failed to start: {self.server_error}")

        metadata_manager = MetadataManager()

        # Subscribe to Temperature node
        topics = {"Temperature"}

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=self.port,
            topics=topics,
            exclude_topics=[],
            interval=1,
        )

        watcher.start()

        # Verify connection
        self.assertTrue(wait_for(lambda: watcher._sub is not None))
        self.assertIsNotNone(watcher._client)

        watcher.stop()

    def test_opc_watcher_receives_data(self):
        """Test that OPCWatcher receives data changes"""
        if self.server_failed:
            self.skipTest(f"OPC demo server failed to start: {self.server_error}")

        received_messages = []

        def callback(topic, data):
            received_messages.append((topic, data))

        metadata_manager = MetadataManager()

        topics = {"Temperature", "Pressure"}

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=self.port,
            topics=topics,
            exclude_topics=[],
            interval=1,
            callbacks=[callback],
        )

        watcher.start()
        self.assertTrue(wait_for(lambda: len(received_messages) > 0), "No initial values received")

        # A server-side change must arrive as a new message
        before = len(received_messages)
        self.demo_server.update_values_once()
        self.assertTrue(wait_for(lambda: len(received_messages) > before), "No data change received")

        watcher.stop()

        # Verify message structure
        for topic, data in received_messages:
            self.assertIn("node", data)
            self.assertIn("value", data)
            self.assertIn("timestamp", data)

    def test_opc_watcher_multiple_updates(self):
        """Test that OPCWatcher receives multiple data updates"""
        if self.server_failed:
            self.skipTest(f"OPC demo server failed to start: {self.server_error}")

        received_messages = []

        def callback(topic, data):
            received_messages.append((topic, data))

        metadata_manager = MetadataManager()

        topics = {"Counter"}

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=self.port,
            topics=topics,
            exclude_topics=[],
            interval=1,
            callbacks=[callback],
        )

        watcher.start()
        self.assertTrue(wait_for(lambda: len(received_messages) > 0), "No initial value received")

        # Every counter increment must arrive as its own message
        for i in range(3):
            before = len(received_messages)
            self.demo_server.update_values_once()
            self.assertTrue(
                wait_for(lambda before=before: len(received_messages) > before), f"Update {i + 1} not received"
            )

        watcher.stop()

    def test_opc_watcher_exclude_topics(self):
        """Test that OPCWatcher excludes specified topics"""
        if self.server_failed:
            self.skipTest(f"OPC demo server failed to start: {self.server_error}")

        received_messages = []

        def callback(topic, data):
            received_messages.append((topic, data))

        metadata_manager = MetadataManager()

        topics = {"Temperature", "Pressure", "Status"}
        exclude_topics = ["Status"]

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=self.port,
            topics=topics,
            exclude_topics=exclude_topics,
            interval=1,
            callbacks=[callback],
        )

        watcher.start()

        # Once both included topics report in, subscribing is done
        def seen():
            return {str(data.get("node")) for _, data in received_messages}

        self.assertTrue(wait_for(lambda: {"Temperature", "Pressure"} <= seen()), f"Only saw {seen()}")
        self.demo_server.update_values_once()
        watcher.stop()

        # Verify that excluded topic was not subscribed
        for topic, data in received_messages:
            node_id = data.get("node", "")
            self.assertNotIn("Status", str(node_id))

    def test_opc_watcher_invalid_connection(self):
        """Test that OPCWatcher handles invalid connection gracefully"""
        metadata_manager = MetadataManager()

        topics = {"Temperature"}

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=9999,  # Invalid port
            topics=topics,
            exclude_topics=[],
            interval=1,
        )

        # Errors are handled by the background reconnect loop; start() itself must not raise.
        watcher.start()
        # Absence check: give it a second to (wrongly) subscribe
        self.assertFalse(wait_for(lambda: watcher._sub is not None, timeout=1))
        self.assertTrue(watcher._thread is not None and watcher._thread.is_alive())
        watcher.stop()

    def test_opc_watcher_no_topics_only_browses(self):
        """Without topics the watcher lists the server's nodes but subscribes to nothing"""
        metadata_manager = MetadataManager()

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=self.port,
            topics=set(),  # Empty topics
            exclude_topics=[],
            interval=1,
        )

        # Without topics the watcher only browses and logs what is available; it never subscribes.
        watcher.start()
        self.assertTrue(wait_for(lambda: len(watcher._all_topics) > 0))
        self.assertIsNone(watcher._sub)
        watcher.stop()


@unittest.skipIf(not OPCUA_AVAILABLE, "OPC UA library not available")
class TestOPCWatcherAuthentication(unittest.TestCase):
    """OPCWatcher against a demo server that requires a username and password."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.demo_server = OPCDemoServer(host="127.0.0.1", port=cls.port, users={"leaf": "secret"})
        cls.demo_server.start()

    @classmethod
    def tearDownClass(cls):
        cls.demo_server.stop()

    def _received(self, username=None, password=None, timeout=5.0):
        """Run a watcher for a few seconds; return the messages it received."""
        received = []
        watcher = OPCWatcher(
            metadata_manager=MetadataManager(),
            host="127.0.0.1",
            port=self.port,
            topics={"Temperature"},
            exclude_topics=[],
            callbacks=[lambda topic, data: received.append(data)],
            username=username,
            password=password,
        )
        watcher.start()
        wait_for(lambda: len(received) > 0, timeout=timeout)
        watcher.stop()
        return received

    def test_correct_credentials_receive_data(self):
        self.assertTrue(self._received("leaf", "secret"))

    def test_wrong_password_is_rejected(self):
        # Absence check: a rejected login fails within milliseconds, 2 s is plenty
        self.assertEqual(self._received("leaf", "wrong", timeout=2.0), [])

    # No anonymous-rejection test: the opcua demo server still admits anonymous clients
    # even with set_security_IDs(["Username"]), so it can't verify that here.


if __name__ == "__main__":
    unittest.main()
