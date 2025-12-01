import os
import random
import socket
import sys
import threading
import time
import unittest
from unittest import skipIf

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.opc_watcher import OPCWatcher
from leaf_register.metadata import MetadataManager

# Import OPC UA library
try:
    from opcua import Server
    OPCUA_AVAILABLE = True
except ImportError:
    OPCUA_AVAILABLE = False
    Server = None

# Check if OPC server is available
def is_opc_server_available(host="127.0.0.1", port=4841, timeout=0.5):
    """Check if an OPC UA server is running at the specified host and port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False

OPC_SERVER_AVAILABLE = is_opc_server_available()


class OPCDemoServer:
    """Demo OPC UA Server for testing"""

    def __init__(self, host="0.0.0.0", port=4840):
        if not OPCUA_AVAILABLE:
            raise ImportError("OPC UA library not available")

        self.host = host
        self.port = port
        self.server = Server()
        self.server.set_endpoint(f"opc.tcp://{host}:{port}/freeopcua/server/")
        self.server.set_server_name("Leaf OPC UA Test Server")

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
        self.temperature_node = demo_object.add_variable(
            ua.NodeId("Temperature", self.idx), "Temperature", 20.0
        )
        self.pressure_node = demo_object.add_variable(
            ua.NodeId("Pressure", self.idx), "Pressure", 101.3
        )
        self.status_node = demo_object.add_variable(
            ua.NodeId("Status", self.idx), "Status", "Running"
        )
        self.counter_node = demo_object.add_variable(
            ua.NodeId("Counter", self.idx), "Counter", 0
        )

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
            cls.demo_server = OPCDemoServer(host="127.0.0.1", port=4841)
            cls.demo_server.start()
            time.sleep(2)  # Give server time to start
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
                time.sleep(0.5)
            except Exception as e:
                print(f"Error stopping OPC demo server: {e}")

    # Skip tests if server failed to start
    @skipIf(OPCUA_AVAILABLE and not OPC_SERVER_AVAILABLE, "OPC UA server not available")
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
            port=4841,
            topics=topics,
            exclude_topics=[],
            interval=1
        )

        watcher.start()
        time.sleep(0.5)

        # Verify connection
        self.assertIsNotNone(watcher._client)
        self.assertIsNotNone(watcher._sub)

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
            port=4841,
            topics=topics,
            exclude_topics=[],
            interval=1,
            callbacks=[callback]
        )

        watcher.start()
        time.sleep(0.5)

        # Update server values
        self.demo_server.update_values_once()
        time.sleep(2)  # Wait for subscription to trigger

        watcher.stop()

        # Should have received at least initial values
        self.assertTrue(len(received_messages) > 0,
                       f"Expected messages but got {len(received_messages)}")

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
            port=4841,
            topics=topics,
            exclude_topics=[],
            interval=1,
            callbacks=[callback]
        )

        watcher.start()
        time.sleep(0.5)

        # Update values multiple times
        for _ in range(3):
            self.demo_server.update_values_once()
            time.sleep(1.5)

        watcher.stop()

        # Should have received multiple updates (initial + 3 updates)
        self.assertTrue(len(received_messages) >= 3,
                       f"Expected at least 3 messages but got {len(received_messages)}")

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
            port=4841,
            topics=topics,
            exclude_topics=exclude_topics,
            interval=1,
            callbacks=[callback]
        )

        watcher.start()
        time.sleep(1)

        self.demo_server.update_values_once()
        time.sleep(2)

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
            interval=1
        )

        # Should raise an exception when trying to connect
        with self.assertRaises(Exception):
            watcher.start()

    def test_opc_watcher_no_topics_raises_error(self):
        """Test that OPCWatcher raises error when no topics provided"""
        metadata_manager = MetadataManager()

        watcher = OPCWatcher(
            metadata_manager=metadata_manager,
            host="127.0.0.1",
            port=4841,
            topics=set(),  # Empty topics
            exclude_topics=[],
            interval=1
        )

        # Should raise ValueError when no topics provided
        with self.assertRaises(ValueError):
            watcher.start()


if __name__ == "__main__":
    unittest.main()