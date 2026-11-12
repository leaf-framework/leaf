import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.security import is_local

logger = get_logger(__name__, log_file="input_module.log")

if TYPE_CHECKING:
    from opcua import Client, Node, Subscription  # pyright: ignore[reportMissingTypeStubs]
    from opcua.common.subscription import DataChangeNotif  # pyright: ignore[reportMissingTypeStubs]
    from opcua.ua import NodeId  # pyright: ignore[reportMissingTypeStubs]

try:
    from opcua import Client, Node, Subscription  # pyright: ignore[reportMissingTypeStubs]
    from opcua.common.subscription import DataChangeNotif  # pyright: ignore[reportMissingTypeStubs]
    from opcua.ua import NodeId  # pyright: ignore[reportMissingTypeStubs]

    OPCUA_AVAILABLE = True
    # Suppress OPC UA library logging to avoid cluttering the output
    logging.getLogger("opcua").setLevel(logging.WARNING)
except ImportError:
    logger.warning("OPC UA library not available. OPCWatcher will not function.")
    OPCUA_AVAILABLE = False
    # Runtime placeholders only; hidden from type checkers so the opcua types stay usable.
    if not TYPE_CHECKING:
        Client = Node = Subscription = DataChangeNotif = NodeId = None

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher

FIRST_RECONNECT_DELAY = 1
RECONNECT_RATE = 2
MAX_RECONNECT_DELAY = 60
KEEPALIVE_INTERVAL = 10


def _node_id(node: Node) -> NodeId:
    """Return the node's id; opcua types it as optional, but a real node always has one."""
    node_id: object = getattr(node, "nodeid", None)
    if not isinstance(node_id, NodeId):
        raise ValueError("OPC UA node has no node id.")
    return node_id


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
        username: str | None = None,
        password: str | None = None,
        security: str | None = None,
        certificate: str | None = None,
        private_key: str | None = None,
    ) -> None:
        """
        Initialize OPCWatcher.

        Args:
            metadata_manager (MetadataManager): Manages equipment metadata.
            callbacks (Optional[List[Callable]]): Callbacks for event updates.
            error_holder (Optional[ErrorHolder]): Optional object to manage errors.
            username (Optional[str]): OPC UA username; anonymous login when omitted.
            password (Optional[str]): Password for the given username.
            security (Optional[str]): Secure channel as "Policy,Mode,cert,key[,server_cert]",
                e.g. "Basic256Sha256,SignAndEncrypt,client.pem,client_key.pem". Needs `cryptography`.
            certificate (Optional[str]): Client certificate path for certificate login.
            private_key (Optional[str]): Private key path belonging to `certificate`.
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
        self._username: str | None = username
        self._password: str | None = password
        self._security: str | None = security
        self._certificate: str | None = certificate
        self._private_key: str | None = private_key
        self.logger = get_logger(__name__, log_file="input_module.log")
        if host is None or port is None:
            raise ValueError("Host and port must be specified.")
        self._client: Client | None = None
        # True once connected and subscribed, False from the first failure on.
        self._connected: bool = False
        self._thread: threading.Thread | None = None
        # Waits use this instead of time.sleep so stop() can wake the thread at once.
        self._stop_event: threading.Event = threading.Event()

    def datachange_notification(self, node: Node, val: int | str | float, data: DataChangeNotif) -> None:
        node_id = _node_id(node)
        self.logger.debug(f"OPC datachange_notification: node={node_id.Identifier}, value={val}")
        self._dispatch_callback(
            self._metadata_manager.measurement,
            {
                "node": node_id.Identifier,
                "value": val,
                "timestamp": data.monitored_item.Value.SourceTimestamp,
                "data": data,
            },
        )

    def security_warnings(self) -> list[str]:
        if is_local(self._host):
            return []
        issues: list[str] = []
        if not self._security:
            issues.append(f"OPC UA to {self._host}: traffic unencrypted, set security")
        if not self._username and not self._certificate:
            issues.append(f"OPC UA to {self._host}: anonymous login, set username/password or certificate")
        return issues

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
        self._stop_event.clear()
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
                self._client = self._new_client()
                self._client.connect()

                root = self._client.get_root_node()
                if not self._topics:
                    self.logger.info("No topics provided. Browsing all topics.")
                    self._all_topics = self._browse_and_read(root)
                    for topic in self._all_topics:
                        self.logger.info(f"Found topic: {topic}")
                    raise ValueError("No topics provided. Please provide a list of topics to subscribe to.")

                self._subscribe_to_topics()
                self._connected = True

                # Reset backoff on successful connection
                reconnect_delay = FIRST_RECONNECT_DELAY
                self.logger.info("OPC UA connected and subscribed. Monitoring...")

                # Keepalive loop — detect silent disconnections
                while self._running:
                    _ = self._stop_event.wait(KEEPALIVE_INTERVAL)
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
            _ = self._stop_event.wait(reconnect_delay)
            reconnect_delay = min(reconnect_delay * RECONNECT_RATE, MAX_RECONNECT_DELAY)

    def _new_client(self) -> Client:
        """Create an OPC UA client with the configured secure channel and login."""
        client = Client(f"opc.tcp://{self._host}:{self._port}")
        if self._security:
            client.set_security_string(self._security)
        if self._certificate:
            client.load_client_certificate(self._certificate)
            client.load_private_key(self._private_key)
        if self._username:
            client.set_user(self._username)
            client.set_password(self._password)
        return client

    def is_connected(self) -> bool:
        return self._connected

    def _cleanup_connection(self) -> None:
        """Unsubscribe and disconnect cleanly."""
        self._connected = False
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
                node_id = _node_id(node)
                self.logger.info(f"Subscribed to: {node_id.to_string()}")
                # Send a dummy value to trigger the callback
                self._dispatch_callback(
                    self._metadata_manager.measurement,
                    {
                        "node": node_id.Identifier,
                        "value": node.get_value(),
                        "timestamp": time.time(),
                        "data": None,
                    },
                )

            except Exception as e:
                self.logger.error(f"Failed to subscribe to {topic}: {e}")
                if "ServiceFault" in str(e):
                    self.logger.info("Retrying in 5 seconds...")
                    _ = self._stop_event.wait(5)
                    continue  # Try the next topic

    def stop(self) -> None:
        """
        Stop the OPCWatcher and disconnect from the OPC UA server.
        """
        self.logger.info("Stopping OPCWatcher")
        super().stop()  # sets _running = False, exits connection loop
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._cleanup_connection()
