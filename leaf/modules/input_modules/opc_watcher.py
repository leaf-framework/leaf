import threading
import time
from collections.abc import Callable
from typing import Any

from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")

try:
    from opcua import Client, Node, Subscription  # type: ignore
    from opcua.ua import DataChangeNotification  # type: ignore

    OPCUA_AVAILABLE = True
    # Suppress OPC UA library logging to avoid cluttering the output
    import logging

    logging.getLogger("opcua").setLevel(logging.WARNING)
except ImportError:
    logger.warning("OPC UA library not available. OPCWatcher will not function.")
    OPCUA_AVAILABLE = False
    Client = Node = Subscription = DataChangeNotification = None  # Placeholders

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher

FIRST_RECONNECT_DELAY = 1
RECONNECT_RATE = 2
MAX_RECONNECT_DELAY = 60
KEEPALIVE_INTERVAL = 10


class OPCWatcher(EventWatcher):
    """
    A concrete implementation of EventWatcher that uses
    predefined fetchers to retrieve and monitor data.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager,
        host: str,
        port: int,
        topics: set[str],
        exclude_topics: list[str],
        interval: int = 1,
        callbacks: list[Callable[..., Any]] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize OPCWatcher.

        Args:
            metadata_manager (MetadataManager): Manages equipment metadata.
            callbacks (Optional[List[Callable]]): Callbacks for event updates.
            error_holder (Optional[ErrorHolder]): Optional object to manage errors.
        """
        super().__init__(metadata_manager, callbacks=callbacks, error_holder=error_holder)

        self._host = host
        self._port = port
        self._topics: set[str] = set(topics)
        self._all_topics: set[str] = set()
        self._exclude_topics: list[str] = exclude_topics
        self._metadata_manager = metadata_manager
        self._sub: Subscription | None = None
        self._handler = self._dispatch_callback
        self._handles: list[Any] = []
        self._interval = interval
        self.logger = get_logger(__name__, log_file="input_module.log")
        if host is None or port is None:
            raise ValueError("Host and port must be specified.")
        self._client: Client | None = None
        self._thread: threading.Thread | None = None

    def datachange_notification(self, node: Node, val: int | str | float, data: DataChangeNotification) -> None:
        self.logger.debug(f"OPC datachange_notification: node={node.nodeid.Identifier}, value={val}")
        self._dispatch_callback(
            self._metadata_manager.measurement,
            {
                "node": node.nodeid.Identifier,
                "value": val,
                "timestamp": data.monitored_item.Value.SourceTimestamp,
                "data": data,
            },
        )

    def start(self) -> None:
        """
        Start the OPCWatcher in a background thread with automatic reconnection.
        """
        if not OPCUA_AVAILABLE:
            raise Exception("OPC UA library is not available. Cannot start OPCWatcher.")

        if self._thread and self._thread.is_alive():
            self.logger.warning("OPCWatcher already running.")
            return

        super().start()
        self._thread = threading.Thread(target=self._connection_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"OPCWatcher started for {self._host}:{self._port}")

    def _connection_loop(self) -> None:
        """
        Main connection loop with automatic reconnection on failure.

        Mirrors the BLE watcher pattern: connect, subscribe, keepalive,
        and retry with exponential backoff if anything goes wrong.
        """
        reconnect_delay = FIRST_RECONNECT_DELAY

        while self._running:
            self.logger.info(f"Connecting to OPC UA server {self._host}:{self._port}...")
            try:
                self._client = Client(f"opc.tcp://{self._host}:{self._port}")
                self._client.connect()

                root = self._client.get_root_node()
                if not self._topics:
                    self.logger.info("No topics provided. Browsing all topics.")
                    self._all_topics = self._browse_and_read(root)
                    for topic in self._all_topics:
                        self.logger.info(f"Found topic: {topic}")
                    raise ValueError("No topics provided. Please provide a list of topics to subscribe to.")

                self._subscribe_to_topics()

                # Reset backoff on successful connection
                reconnect_delay = FIRST_RECONNECT_DELAY
                self.logger.info("OPC UA connected and subscribed. Monitoring...")

                # Keepalive loop — detect silent disconnections
                while self._running:
                    time.sleep(KEEPALIVE_INTERVAL)
                    try:
                        self._client.get_root_node().get_browse_name()
                    except Exception as e:
                        self.logger.warning(f"OPC UA keepalive failed, reconnecting: {e}")
                        break  # exit keepalive loop → triggers reconnect

            except Exception as e:
                self.logger.error(f"OPC UA connection error: {e}")

            finally:
                self._cleanup_connection()

            if not self._running:
                break

            self.logger.info(f"Reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * RECONNECT_RATE, MAX_RECONNECT_DELAY)

    def _cleanup_connection(self) -> None:
        """Unsubscribe and disconnect cleanly."""
        if self._sub and self._handles:
            try:
                for handle in self._handles:
                    self._sub.unsubscribe(handle)
                self._handles.clear()
            except Exception as e:
                self.logger.debug(f"Error unsubscribing: {e}")

        if self._sub:
            try:
                self._sub.delete()
            except Exception as e:
                self.logger.debug(f"Error deleting subscription: {e}")
            self._sub = None

        if self._client:
            try:
                self._client.disconnect()
            except Exception as e:
                self.logger.debug(f"Error disconnecting: {e}")
            self._client = None

    def _browse_and_read(self, node: Node) -> set[str]:
        """
        Recursively browse and read OPC UA nodes to obtain topics.

        Returns:
            Set[str]: A set of node identifiers (NodeIds) in format "ns=X;s=identifier".
        """
        nodes_data = set()
        for child in node.get_children():
            browse_name = child.get_browse_name().Name
            if browse_name == "Server":
                continue
            try:
                child.get_value()
                # Store full NodeId string including namespace
                full_nodeid = child.nodeid.to_string()
                nodes_data.add(full_nodeid)
                logger.info(f"Found topic: '{full_nodeid}'")
            except Exception as e:
                # Skip nodes that don't support value reading (organizational nodes, etc.)
                if "BadAttributeIdInvalid" in str(e):
                    self.logger.debug(f"Skipping node {child.nodeid} - doesn't support value reading")
                else:
                    self.logger.error(f"Error reading node {child.nodeid}: {e}")
                pass
            nodes_data.update(self._browse_and_read(child))  # Recursive call
        return nodes_data

    def _subscribe_to_topics(self) -> None:
        """
        Subscribe to OPC UA nodes and monitor data changes.
        """
        if not self._client:
            self.logger.warning("Client is not connected.")
            return

        self._sub = self._client.create_subscription(self._interval * 1000, self)  # second interval converted to ms

        for topic in self._topics:
            if topic in self._exclude_topics:
                self.logger.info(f"Excluded topic: {topic}")
                continue
            try:
                # Support both full NodeId format (ns=2;s=topic) and simple topic names
                if topic.startswith("ns=") or topic.startswith("i="):
                    logger.debug(f"Full NodeId format provided: {topic}")
                    node = self._client.get_node(topic)
                else:
                    logger.debug(f"Simple topic name provided, subscribing to ns=2;s={topic}")
                    node = self._client.get_node(f"ns=2;s={topic}")

                handle = self._sub.subscribe_data_change(node)
                self._handles.append(handle)
                self.logger.info(f"Subscribed to: {node.nodeid.to_string()}")
                # Send a dummy value to trigger the callback
                self._dispatch_callback(
                    self._metadata_manager.measurement,
                    {
                        "node": node.nodeid.Identifier,
                        "value": node.get_value(),
                        "timestamp": time.time(),
                        "data": None,
                    },
                )

            except Exception as e:
                self.logger.error(f"Failed to subscribe to {topic}: {e}")
                if "ServiceFault" in str(e):
                    self.logger.info("Retrying in 5 seconds...")
                    time.sleep(5)
                    continue  # Try the next topic

    def stop(self) -> None:
        """
        Stop the OPCWatcher and disconnect from the OPC UA server.
        """
        self.logger.info("Stopping OPCWatcher")
        super().stop()  # sets _running = False, exits connection loop

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._cleanup_connection()
