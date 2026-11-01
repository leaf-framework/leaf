import time
from collections.abc import Callable
from socket import gaierror
from typing import Any, Literal
from uuid import uuid4

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, ClientUnreachableError, LEAFError, SeverityLevel
from leaf.modules.input_modules.external_event_watcher import ExternalEventWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


class MQTTExternalEventWatcher(ExternalEventWatcher):
    def __init__(
        self,
        metadata_manager: MetadataManager = None,
        broker: str = None,
        topics: list = None,
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

        self._topics = topics
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
        self._client_id: str | None = clientid
        self._broker: str = broker
        self._port: int = port
        self._username: str | None = username
        self._password: str | None = password
        self._tls: bool = tls
        self.messages: dict[str, list[str]] = {}

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

        self._username = None
        self._password = None
        if username and password:
            self._username = username
            self._password = password

        if tls:
            try:
                self.client.tls_set()
                self.client.tls_insecure_set(True)
            except Exception as e:
                raise AdapterBuildError(f"Failed to set up TLS: {e}")

    def start(self):
        """
        Connects to the MQTT broker and sets a thread looping.
        """
        try:
            if self._username and self._password:
                self.client.username_pw_set(self._username, self._password)
            self.client.connect(self._broker, self._port, 60)
            self.client.loop_start()
            time.sleep(3)
            for topic in self._topics:
                self.subscribe(topic)
                time.sleep(0.1)

        except (gaierror, OSError) as e:
            self._handle_exception(ClientUnreachableError(f"Error connecting to broker: {e}", output_module=self))

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
        payload = msg.payload.decode()
        topic = msg.topic
        for cb in self._callbacks:
            cb(topic, payload)

    def subscribe(self, topic: str) -> str:
        """
        Subscribe to a topic on the MQTT broker.

        Args:
            topic (str): The topic to subscribe to.

        Returns:
            str: The subscribed topic.
        """
        logger.debug(f"Subscribing to {topic}")
        self.client.subscribe(topic)
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

    def on_connect_fail(
        self,
        flags: dict,
        rc: int,
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

    def is_connected(self) -> bool:
        """
        Check if the MQTT client is connected.

        Returns:
            bool: True if the client is connected, False otherwise.
        """
        return self.client.is_connected()
