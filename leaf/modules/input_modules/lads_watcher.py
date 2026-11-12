import threading
import time
from collections.abc import Callable
from typing import Any

from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.security import is_local

logger = get_logger(__name__, log_file="input_module.log")

try:
    from opcua import Client, Node, Subscription, ua  # type: ignore
    from opcua.ua import DataChangeNotification  # type: ignore

    OPCUA_AVAILABLE = True
    # Suppress OPC UA library logging to avoid cluttering the output
    import logging

    logging.getLogger("opcua").setLevel(logging.WARNING)
except ImportError:
    logger.warning("OPC UA library not available. LADSWatcher will not function.")
    OPCUA_AVAILABLE = False
    Client = Node = Subscription = DataChangeNotification = ua = None  # Placeholders

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.event_watcher import EventWatcher

FIRST_RECONNECT_DELAY = 1
RECONNECT_RATE = 2
MAX_RECONNECT_DELAY = 60
KEEPALIVE_INTERVAL = 10

# Standard LADS subtrees that hold configuration/metadata rather than live
# measurement data (locking, historizing config, program templates, static
# state-machine descriptors) - excluded from discovery by default.
SKIP_BROWSE_NAMES = {
    "Lock",
    "HA Configuration",
    "ProgramTemplateSet",
    "AvailableStates",
    "AvailableTransitions",
}


class LADSWatcher(EventWatcher):
    """
    A concrete implementation of EventWatcher for OPC UA LADS (IEC 63243)
    lab-device servers. Unlike OPCWatcher, which requires callers to supply
    exact NodeIds, LADSWatcher discovers monitorable variables automatically
    by walking the standard LADS DeviceSet -> FunctionalUnitSet -> FunctionSet
    structure.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager,
        host: str,
        port: int,
        functional_units: set[str] | None = None,
        exclude_variables: list[str] | None = None,
        interval: int = 1,
        callbacks: list[Callable[..., Any]] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize LADSWatcher.

        Args:
            metadata_manager (MetadataManager): Manages equipment metadata.
            host (str): LADS OPC UA server host.
            port (int): LADS OPC UA server port.
            functional_units (Optional[set[str]]): Names of functional units to
                monitor. If None, all discovered functional units are monitored.
            exclude_variables (Optional[list[str]]): Variable browse names to
                exclude from discovery (e.g. "RawValue").
            callbacks (Optional[List[Callable]]): Callbacks for event updates.
            error_holder (Optional[ErrorHolder]): Optional object to manage errors.
        """
        super().__init__(metadata_manager, callbacks=callbacks, error_holder=error_holder)

        self._host = host
        self._port = port
        self._functional_units: set[str] | None = set(functional_units) if functional_units else None
        self._exclude_variables: list[str] = exclude_variables or []
        self._metadata_manager = metadata_manager
        self._sub: Subscription | None = None
        self._handler = self._dispatch_callback
        self._handles: list[Any] = []
        self._interval = interval
        self.logger = get_logger(__name__, log_file="input_module.log")
        if host is None or port is None:
            raise ValueError("Host and port must be specified.")
        self._client: Client | None = None
        # True once connected and subscribed, False from the first failure on.
        self._connected: bool = False
        self._thread: threading.Thread | None = None
        # NodeId string -> {"functional_unit": str, "browse_name": str, "node": Node}
        self._variables: dict[str, dict[str, Any]] = {}

    def datachange_notification(self, node: Node, val: int | str | float, data: DataChangeNotification) -> None:
        nodeid = node.nodeid.to_string()
        self.logger.debug(f"LADS datachange_notification: node={nodeid}, value={val}")
        info = self._variables.get(nodeid, {})
        self._dispatch_callback(
            self._metadata_manager.measurement,
            {
                "functional_unit": info.get("functional_unit"),
                "node": node.nodeid.Identifier,
                "value": val,
                "timestamp": data.monitored_item.Value.SourceTimestamp,
                "data": data,
            },
        )

    def security_warnings(self) -> list[str]:
        if is_local(self._host):
            return []
        # LADS has no login or encryption options yet, so there is no setting to point to.
        return [f"LADS to {self._host}: anonymous and unencrypted, keep it on a trusted network"]

    def start(self) -> None:
        """
        Start the LADSWatcher in a background thread with automatic reconnection.
        """
        if not OPCUA_AVAILABLE:
            raise Exception("OPC UA library is not available. Cannot start LADSWatcher.")

        if self._thread and self._thread.is_alive():
            self.logger.warning("LADSWatcher already running.")
            return

        super().start()
        self._thread = threading.Thread(target=self._connection_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"LADSWatcher started for {self._host}:{self._port}")

    def _connection_loop(self) -> None:
        """
        Main connection loop with automatic reconnection on failure.

        Mirrors OPCWatcher's pattern: connect, discover, subscribe, keepalive,
        and retry with exponential backoff if anything goes wrong.
        """
        reconnect_delay = FIRST_RECONNECT_DELAY

        while self._running:
            self.logger.info(f"Connecting to LADS OPC UA server {self._host}:{self._port}...")
            try:
                self._client = Client(f"opc.tcp://{self._host}:{self._port}")
                self._client.connect()

                objects = self._client.get_objects_node()
                self._variables = self._discover_variables(objects)
                if not self._variables:
                    raise ValueError("No LADS functional unit variables discovered on server.")

                self._subscribe_to_variables()
                self._connected = True

                # Reset backoff on successful connection
                reconnect_delay = FIRST_RECONNECT_DELAY
                self.logger.info(
                    f"LADS OPC UA connected and subscribed to {len(self._variables)} variables. Monitoring..."
                )

                # Keepalive loop — detect silent disconnections
                while self._running:
                    time.sleep(KEEPALIVE_INTERVAL)
                    try:
                        self._client.get_root_node().get_browse_name()
                    except Exception as e:
                        self.logger.warning(f"LADS OPC UA keepalive failed, reconnecting: {e}")
                        break  # exit keepalive loop → triggers reconnect

            except Exception as e:
                self.logger.error(f"LADS OPC UA connection error: {e}")

            finally:
                self._cleanup_connection()

            if not self._running:
                break

            self.logger.info(f"Reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * RECONNECT_RATE, MAX_RECONNECT_DELAY)

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

        self._variables = {}

    def _browse_device_set(self, objects: Node) -> list[Node]:
        """
        Return device nodes under Objects/DeviceSet. A device is identified
        structurally (an Object with a FunctionalUnitSet child) rather than by
        name, since DeviceSet can also contain non-device components such as
        DeviceFeatures.
        """
        device_set = None
        for child in objects.get_children():
            if child.get_browse_name().Name == "DeviceSet":
                device_set = child
                break
        if device_set is None:
            return []

        devices = []
        for child in device_set.get_children():
            if child.get_node_class() != ua.NodeClass.Object:
                continue
            if any(gc.get_browse_name().Name == "FunctionalUnitSet" for gc in child.get_children()):
                devices.append(child)
        return devices

    def _browse_functional_units(self, device_node: Node) -> dict[str, Node]:
        """Return {functional_unit_name: node} for a device's FunctionalUnitSet."""
        units: dict[str, Node] = {}
        for child in device_node.get_children():
            if child.get_browse_name().Name != "FunctionalUnitSet":
                continue
            for fu in child.get_children():
                if fu.get_node_class() != ua.NodeClass.Object:
                    continue
                units[fu.get_browse_name().Name] = fu
        return units

    def _walk_variables(self, node: Node, visited: set[str], found: dict[str, Node]) -> None:
        """
        Recursively collect readable Variable nodes under a functional unit.

        LADS nodesets reference the same object through multiple reference
        types (e.g. Organizes + HasComponent), so naive recursion without a
        visited-set revisits and duplicates nodes.
        """
        nodeid = node.nodeid.to_string()
        if nodeid in visited:
            return
        visited.add(nodeid)

        try:
            browse_name = node.get_browse_name().Name
        except Exception as e:
            self.logger.debug(f"Skipping node {node.nodeid}, could not read browse name: {e}")
            return

        if browse_name in SKIP_BROWSE_NAMES:
            return

        try:
            node_class = node.get_node_class()
        except Exception as e:
            self.logger.debug(f"Skipping node {node.nodeid}, could not read node class: {e}")
            return

        if node_class == ua.NodeClass.Variable:
            if browse_name not in self._exclude_variables:
                found[nodeid] = node
            # Variables may have child properties (EngineeringUnits, EURange)
            # that aren't independently useful measurements - don't recurse.
            return

        if node_class != ua.NodeClass.Object:
            return

        for child in node.get_children():
            self._walk_variables(child, visited, found)

    def _discover_variables(self, objects: Node) -> dict[str, dict[str, Any]]:
        """
        Walk Objects/DeviceSet -> device -> FunctionalUnitSet -> functional
        units, collecting readable Variable nodes for each functional unit
        (filtered by self._functional_units if provided).
        """
        variables: dict[str, dict[str, Any]] = {}
        for device in self._browse_device_set(objects):
            units = self._browse_functional_units(device)
            for fu_name, fu_node in units.items():
                if self._functional_units and fu_name not in self._functional_units:
                    self.logger.info(f"Excluded functional unit: {fu_name}")
                    continue
                visited: set[str] = set()
                found: dict[str, Node] = {}
                self._walk_variables(fu_node, visited, found)
                for nodeid, node in found.items():
                    variables[nodeid] = {
                        "functional_unit": fu_name,
                        "browse_name": node.get_browse_name().Name,
                        "node": node,
                    }
                    self.logger.info(f"Found variable: {fu_name}/{node.get_browse_name().Name} ({nodeid})")
        return variables

    def _subscribe_to_variables(self) -> None:
        """
        Subscribe to discovered LADS variables and monitor data changes.
        """
        if not self._client:
            self.logger.warning("Client is not connected.")
            return

        self._sub = self._client.create_subscription(self._interval * 1000, self)  # second interval converted to ms

        for nodeid, info in self._variables.items():
            node = info["node"]
            try:
                handle = self._sub.subscribe_data_change(node)
                self._handles.append(handle)
                self.logger.info(f"Subscribed to: {info['functional_unit']}/{info['browse_name']} ({nodeid})")
                # Send a dummy value to trigger the callback
                self._dispatch_callback(
                    self._metadata_manager.measurement,
                    {
                        "functional_unit": info["functional_unit"],
                        "node": node.nodeid.Identifier,
                        "value": node.get_value(),
                        "timestamp": time.time(),
                        "data": None,
                    },
                )

            except Exception as e:
                self.logger.error(f"Failed to subscribe to {nodeid}: {e}")
                if "ServiceFault" in str(e):
                    self.logger.info("Retrying in 5 seconds...")
                    time.sleep(5)
                    continue  # Try the next variable

    def stop(self) -> None:
        """
        Stop the LADSWatcher and disconnect from the OPC UA server.
        """
        self.logger.info("Stopping LADSWatcher")
        super().stop()  # sets _running = False, exits connection loop

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._cleanup_connection()
