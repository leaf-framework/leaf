
import time
from typing import Optional, Callable, List, Any, Set

from leaf_register.metadata import MetadataManager

from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")

try:
    from opcua import Client, Node, Subscription  # type: ignore
    from opcua.ua import DataChangeNotification   # type: ignore
    OPCUA_AVAILABLE = True
    # Suppress OPC UA library logging to avoid cluttering the output
    import logging
    logging.getLogger('opcua').setLevel(logging.WARNING)
except ImportError:
    logger.warning("OPC UA library not available. OPCWatcher will not function.")
    OPCUA_AVAILABLE = False
    Client = Node = Subscription = DataChangeNotification = None  # Placeholders

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher

class OPCWatcher(EventWatcher):
    """
    A concrete implementation of EventWatcher that uses
    predefined fetchers to retrieve and monitor data.
    """

    def __init__(self,
                 metadata_manager: MetadataManager,
                 host: str,
                 port: int,
                 topics: set[str],
                 exclude_topics: list[str],
                 interval: int = 1,
                 callbacks: Optional[List[Callable[..., Any]]] = None,
                 error_holder: Optional[ErrorHolder] = None) -> None:
        """
        Initialize OPCWatcher.

        Args:
            metadata_manager (MetadataManager): Manages equipment metadata.
            callbacks (Optional[List[Callable]]): Callbacks for event updates.
            error_holder (Optional[ErrorHolder]): Optional object to manage errors.
        """
        super().__init__(metadata_manager,
                         callbacks=callbacks,
                         error_holder=error_holder)

        self._host = host
        self._port = port
        self._topics: set[str] = set(topics)
        self._all_topics: set[str] = set()
        self._exclude_topics: list[str] = exclude_topics
        self._metadata_manager = metadata_manager
        self._sub: Subscription|None = None
        self._handler = self._dispatch_callback
        self._handles: list[Any] = []
        self._interval = interval
        self.logger = get_logger(__name__, log_file="input_module.log")
        if host is None or port is None:
            raise ValueError("Host and port must be specified.")
        self._client = Client(f"opc.tcp://{host}:{port}")

    def datachange_notification(self, node: Node, val: int|str|float, data: DataChangeNotification) -> None:
        self.logger.debug(f"OPC datachange_notification: node={node.nodeid.Identifier}, value={val}")
        self._dispatch_callback(self._metadata_manager.experiment.measurement, {
            "node": node.nodeid.Identifier,
            "value":val,
            "timestamp":data.monitored_item.Value.SourceTimestamp,
            "data":data
        })

    def start(self) -> None:
        """
        Start the OPCWatcher
        """
        if not OPCUA_AVAILABLE:
            raise Exception("OPC UA library is not available. Cannot start OPCWatcher.")

        self.logger.info(f"Starting OPCWatcher on {self._host}:{self._port}")
        self._client.connect()

        root = self._client.get_root_node()
        objects_node = root.get_child(["0:Objects"])
        # Automatically browse and read nodes to obtain topics user could provide a list of topics.
        # subscribe_to_topics = set()
        if self._topics is None or len(self._topics) == 0:
            logger.info("No topics provided. Will list all topics.")
            self._all_topics = self._browse_and_read(root)
            for topic in self._all_topics:
                self.logger.info(f"Found topic: {topic}")
            logger.info("Finished listing topics.")
            raise ValueError("No topics provided. Please provide a list of topics to subscribe to.")

        # Subscribe to topics
        self._subscribe_to_topics()

    def _browse_and_read(self, node: Node) -> Set[str]:
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
        try:
            self._sub = self._client.create_subscription(self._interval * 1000, self)  # second interval converted to ms
            # When no topics are provided, report all topics but subscribe to none
            # if not self._topics:
            #     self._topics = self._all_topics

            for topic in self._topics:
                if topic in self._exclude_topics:
                    self.logger.info("Excluded topic: {}".format(topic))
                    continue
                try:
                    # Support both full NodeId format (ns=2;s=topic) and simple topic names
                    if topic.startswith("ns=") or topic.startswith("i="):
                        # Full NodeId format provided
                        logger.debug(f"Full NodeId format provided: {topic}")
                        node = self._client.get_node(topic)
                    else:
                        # Simple topic name, assume ns=2;s= format
                        logger.debug(f"Simple topic name provided, subscribing to ns=2;s={topic}")
                        node = self._client.get_node(f"ns=2;s={topic}")

                    handle = self._sub.subscribe_data_change(node)
                    self._handles.append(handle)
                    self.logger.info(f"Subscribed to: {node.nodeid.to_string()}")
                    # Send a dummy value to trigger the callback
                    self._dispatch_callback(self._metadata_manager.experiment.measurement, {
                        "node": node.nodeid.Identifier,
                        "value": node.get_value(),
                        "timestamp": time.time(),
                        "data": None # Are we using this object in the opc measurement adapter?
                    })

                except Exception as e:
                    self.logger.error(f"Failed to subscribe to {topic}: {e}")
                    if "ServiceFault" in str(e):
                        self.logger.info("Retrying in 5 seconds...")
                        time.sleep(5)
                        continue  # Try the next topic
        except Exception as e:
            self.logger.info(f"Failed to create subscription: {e}")

    def stop(self) -> None:
        """
        Stop the OPCWatcher and disconnect from the OPC UA server.
        """
        self.logger.info("Stopping OPCWatcher")

        # Call parent stop to set _running flag
        super().stop()

        # Unsubscribe from all handles
        if self._sub and self._handles:
            try:
                for handle in self._handles:
                    self._sub.unsubscribe(handle)
                self._handles.clear()
                self.logger.debug("Unsubscribed from all topics")
            except Exception as e:
                self.logger.error(f"Error unsubscribing: {e}")

        # Delete subscription
        if self._sub:
            try:
                self._sub.delete()
                self._sub = None
                self.logger.debug("Deleted subscription")
            except Exception as e:
                self.logger.error(f"Error deleting subscription: {e}")

        # Disconnect client
        if self._client:
            try:
                self._client.disconnect()
                self.logger.info("Disconnected from OPC UA server")
            except Exception as e:
                self.logger.error(f"Error disconnecting client: {e}")