import threading
import time
from collections.abc import Callable
from socket import gaierror
from typing import Any, Literal
from uuid import uuid4

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, ClientUnreachableError, LEAFError, SeverityLevel
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.register.metadata import MetadataManager
from leaf.register.topic_utilities import topic_utilities
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.security import mqtt_warnings

logger = get_logger(__name__, log_file="input_module.log")


class MQTTEventWatcher(EventWatcher):
    def __init__(
        self,
        metadata_manager: MetadataManager,
        start_topics: list[str] | None = None,
        stop_topics: list[str] | None = None,
        measurement_topics: list[str] | None = None,
        error_topics: list[str] | None = None,
        broker: str = None,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        clientid: str | None = None,
        protocol: Literal["v3", "v5"] = "v3",
        transport: Literal["tcp", "websockets", "unix"] = "tcp",
        tls: bool = False,
        callbacks: list[Callable] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        super().__init__(metadata_manager, callbacks=callbacks, error_holder=error_holder)

        if protocol not in ["v3", "v5"]:
            raise AdapterBuildError(f"Unsupported protocol '{protocol}'.")
        self._protocol = mqtt.MQTTv5 if protocol == "v5" else mqtt.MQTTv311

        if transport not in ["tcp", "websockets", "unix"]:
            raise AdapterBuildError(f"Unsupported transport '{transport}'.")

        if not isinstance(broker, str) or not broker:
            raise AdapterBuildError("Broker must be a non-empty string representing the MQTT broker address.")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise AdapterBuildError("Port must be an integer between 1 and 65535.")

        if clientid is None:
            clientid = str(uuid4())

        self._client_id = clientid
        self._broker = broker
        self._port = port
        self._username = None
        self._password = None
        self._tls = tls
        self.messages: dict[str, list[str]] = {}

        if username and password:
            self._username = username
            self._password = password

        client_kwargs: dict[str, Any] = {
            "callback_api_version": CallbackAPIVersion.VERSION2,
            "client_id": clientid,
            "protocol": self._protocol,
            "transport": transport,
        }
        if self._protocol != mqtt.MQTTv5:
            client_kwargs["clean_session"] = True

        self.client = mqtt.Client(**client_kwargs)

        self.client.on_connect = self.on_connect
        self.client.on_connect_fail = self.on_connect_fail
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe

        if tls:
            try:
                self.client.tls_set()
                self.client.tls_insecure_set(True)
            except Exception as e:
                raise AdapterBuildError(f"Failed to set up TLS: {e}")

        # topic -> list of events
        self._topic_event_map: dict[str, list[str]] = {}
        self._register_topics(start_topics, metadata_manager.start)
        self._register_topics(measurement_topics, metadata_manager.measurement)
        self._register_topics(stop_topics, metadata_manager.stop)
        self._register_topics(error_topics, metadata_manager.error)

        # Set when on_connect fires so start() can block until subscriptions are active
        self._connected_event = threading.Event()

        # wait for the SUBACKs instead of just for CONNACK.
        self._pending_subscriptions: set[int] = set()
        self._subscriptions_lock = threading.Lock()
        self._subscribed_event = threading.Event()

    def _register_topics(self, topics: list[str] | None, event: str):
        if topics:
            for topic in topics:
                self._topic_event_map.setdefault(topic, []).append(event)

    def start(self):
        """
        Connects to the MQTT broker and sets a thread looping.
        Blocks until on_connect fires and every subscription has been
        acknowledged by the broker, so callers can publish immediately after
        start() returns.  On reconnects after a broker restart, on_connect
        re-subscribes automatically.
        """
        super().start()
        try:
            if self._username and self._password:
                self.client.username_pw_set(self._username, self._password)
            self.client.connect(self._broker, self._port, 60)
            self.client.loop_start()
            # Both waits are bounded, and a timeout warns and carries on rather
            # than blocking: a broker that accepts the connection but never
            # acknowledges a SUBSCRIBE must not hang the caller. The second
            # wait is skipped when the connect wait already timed out, so the
            # worst case stays 10s rather than doubling.
            if self._connected_event.wait(timeout=10) and not self._subscribed_event.wait(timeout=10):
                logger.warning(
                    f"Timed out waiting for subscription acknowledgement from {self._broker}. "
                    "Continuing anyway - messages published immediately may be missed."
                )
        except (gaierror, OSError) as e:
            self._handle_exception(
                ClientUnreachableError(f"Error connecting to broker: {self._broker} {e}", output_module=self)
            )

    def stop(self) -> None:
        """
        Disconnect from the MQTT broker and stop the threaded loop.
        """
        try:
            if self.client.is_connected():
                self.client.disconnect()
                time.sleep(0.5)
            self.client.loop_stop()
        except Exception:
            self._handle_exception(ClientUnreachableError("Failed to disconnect from broker.", output_module=self))

    def on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """
        Callback for when a message is received on a
        subscribed topic.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as
                            set in Client() or userdata_set().
            msg (mqtt.MQTTMessage): The received MQTT message.
        """
        incoming_topic = msg.topic
        payload = msg.payload.decode()
        full_payload = {"topic": incoming_topic, "payload": payload}

        for registered_topic, events in self._topic_event_map.items():
            if topic_utilities.is_instance(incoming_topic, registered_topic):
                for event in events:
                    for cb in self._callbacks:
                        cb(event, full_payload)

    def subscribe(self, topic: str) -> str:
        """
        Subscribe to a topic on the MQTT broker.

        Args:
            topic (str): The topic to subscribe to.

        Returns:
            str: The subscribed topic.
        """
        logger.debug(f"Subscribing to {topic}")
        _, mid = self.client.subscribe(topic)
        if mid is not None:
            with self._subscriptions_lock:
                self._pending_subscriptions.add(mid)
                self._subscribed_event.clear()
        return topic

    def unsubscribe(self, topic: str) -> str:
        """
        Unsubscribe from a topic on the MQTT broker.

        Args:
            topic (str): The topic to unsubscribe from.

        Returns:
            str: The unsubscribed topic.
        """

        self.client.unsubscribe(topic)
        return topic

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        rc: int,
        metadata: Any | None = None,
    ) -> None:
        """
        Callback for when the client connects to the broker.
        Subscribes to all registered topics here so subscriptions are
        restored automatically after a reconnect (paho reconnects the
        TCP session but does not re-subscribe on clean_session=True).

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
            flags (dict): Response flags sent by the broker.
            rc (int): The connection result code.
            metadata (Optional[Any]): Additional metadata (if any).
        """
        logger.info(f"Connected to broker {self._username}@{self._broker}")

        if rc != 0:
            error_messages = {
                1: "Unacceptable protocol version",
                2: "Client identifier rejected",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized",
            }
            message = error_messages.get(rc.value, f"Unknown connection error with code {rc}")
            self._handle_exception(ClientUnreachableError(f"Connection refused: {message}", output_module=self))
            return

        # Reset before re-subscribing: on_connect also runs on reconnects, and
        # the previous session's mids are meaningless on the new one.
        with self._subscriptions_lock:
            self._pending_subscriptions.clear()
            self._subscribed_event.clear()

        for topic in self._topic_event_map.keys():
            self.subscribe(topic)

        # Nothing to wait for when there are no topics. Safe to check here:
        # on_connect and on_subscribe both run on paho's network thread, so no
        # SUBACK can be processed while this callback is still running.
        with self._subscriptions_lock:
            if not self._pending_subscriptions:
                self._subscribed_event.set()

        self._connected_event.set()

    def on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_code_list: Any | None = None,
        properties: Any | None = None,
    ) -> None:
        """
        Callback for when the broker acknowledges a SUBSCRIBE.

        Clears the mid from the pending set so start() can tell when every
        subscription is actually live, rather than merely requested.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
            mid (int): Message id of the SUBSCRIBE being acknowledged.
            reason_code_list (Optional[Any]): Per-subscription reason codes.
            properties (Optional[Any]): Additional metadata (if any).
        """
        with self._subscriptions_lock:
            self._pending_subscriptions.discard(mid)
            if not self._pending_subscriptions:
                self._subscribed_event.set()

    def on_connect_fail(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        rc: int,
        metadata: Any | None = None,
    ) -> None:
        """
        Callback for when the client fails to connect to the broker.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
            flags (dict): Response flags sent by the broker.
            rc (int): The connection result code.
            metadata (Optional[Any]): Additional metadata (if any).
        """
        logger.error(f"Connection failed: {rc}")
        leaf_error = LEAFError("Failed to connect", SeverityLevel.CRITICAL)
        self._handle_exception(leaf_error)

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: int,
        properties: Any | None = None,
    ) -> None:
        """
        Callback for when the client disconnects from the broker.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
            flags (Any): Response flags sent by the broker.
            rc (int): The disconnection result code.
            properties (Optional[Any]): Additional metadata (if any).
        """
        logger.info(f"Disconnected from broker {self._username}@{self._broker}")
        if rc != mqtt.MQTT_ERR_SUCCESS:
            # paho's loop_start() handles automatic reconnection
            logger.warning(f"Unexpected disconnect (rc={rc}), paho will auto-reconnect")

    def security_warnings(self) -> list[str]:
        return mqtt_warnings("MQTT input", self._broker, self._username, self._tls)

    def is_connected(self) -> bool:
        """
        Check if the MQTT client is connected.

        Returns:
            bool: True if the client is connected, False otherwise.
        """
        return self.client.is_connected()

    def disconnect(self) -> None:
        """
        Disconnect the MQTT client from the broker.
        """
        self.client.disconnect()
        logger.info(f"MQTT client disconnected: {self.client.is_connected()}")

    def connect(self) -> None:
        """
        Connect the MQTT client to the broker.
        """
        self.client.connect(host=self._broker, port=self._port, keepalive=60)
        logger.info(f"MQTT client connected: {self.client.is_connected()}")
