import time
from typing import Optional, Callable, List, Any, Set
import re

from leaf_register.metadata import MetadataManager

try:
    from opcua import Client, Node, Subscription  # type: ignore
    from opcua.ua import DataChangeNotification   # type: ignore
    OPCUA_AVAILABLE = True
    # Suppress OPC UA library logging to avoid cluttering the output
    import logging
    logging.getLogger('opcua').setLevel(logging.WARNING)
except ImportError:
    from leaf.utility.logger.logger_utils import get_logger
    logger = get_logger(__name__, log_file="input_module.log")
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
        from leaf.utility.logger.logger_utils import get_logger
        self.logger = get_logger(__name__, log_file="input_module.log")

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
        self._client = Client(f"opc.tcp://{self._host}:{self._port}")
        self._client.connect()

        root = self._client.get_root_node()
        objects_node = root.get_child(["0:Objects"])
        # Automatically browse and read nodes to obtain topics user could provide a list of topics.
        self._all_topics = self._browse_and_read(objects_node)
        if self._topics is None or len(self._topics) == 0:
            self.logger.info("No topics provided. Will register to all " + str(len(self._all_topics)) + " topics.")
            for topic in self._all_topics:
                self.logger.debug(f"Found topic: {topic}")
        else:
            # Topics are provided by the user
            subscribe_to_topics = set()
            for topic in self._topics:
                # Allow regex matching with the all_topics list
                if topic not in self._all_topics:
                    # Perform regex matching
                    found = False
                    for all_topic in self._all_topics:
                        if re.match("^" + topic + "$", all_topic):
                            subscribe_to_topics.add(all_topic)
                            found = True
                            # no break to allow multiple topics to match but it should at least match one topic
                    # Throw error if no match found
                    if not found:
                        self.logger.error(f"Topic {topic} not found in OPC UA server topics and this adapter will stop.")
                        raise Exception(f"Topic {topic} not found in OPC UA server topics. Available topics: {self._all_topics}")
                else:
                    subscribe_to_topics.add(topic)
            # Update topics
            self._topics = subscribe_to_topics

        # Subscribe to topics
        self._subscribe_to_topics()

    def _browse_and_read(self, node: Node) -> Set[str]:
        """
        Recursively browse and read OPC UA nodes to obtain topics.

        Returns:
            Set[str]: A set of node identifiers (NodeIds).
        """
        nodes_data = set()
        for child in node.get_children():
            browse_name = child.get_browse_name().Name
            if browse_name == "Server":
                continue
            try:
                child.get_value()
                nodes_data.add(child.nodeid.Identifier)
            except Exception as e:
                # Skip nodes that don't support value reading (organizational nodes, etc.)
                if "BadAttributeIdInvalid" in str(e):
                    self.logger.debug(f"Skipping node {child.nodeid.Identifier} - doesn't support value reading")
                else:
                    self.logger.error(f"Error reading node {child.nodeid.Identifier}: {e}")
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
            # When no topics are provided, subscribe to all topics
            if not self._topics:
                self._topics = self._all_topics

            for topic in self._topics:
                if topic in self._exclude_topics:
                    self.logger.info("Excluded topic: {}".format(topic))
                    continue
                try:
                    node = self._client.get_node(f"ns=2;s={topic}")  # Adjust namespace
                    handle = self._sub.subscribe_data_change(node)
                    self._handles.append(handle)
                    self.logger.info(f"Subscribed to: {topic}")
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