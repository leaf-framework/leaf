import logging
from uuid import uuid4
from typing import Optional, List, Callable

import logging
import time
from socket import error as socket_error
from socket import gaierror
from typing import Literal, Optional, Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.utility.logger.logger_utils import get_logger
from leaf_register.metadata import MetadataManager
from leaf_register.topic_utilities import topic_utilities
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, LEAFError
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel

FIRST_RECONNECT_DELAY = 1
RECONNECT_RATE = 2
MAX_RECONNECT_COUNT = 12
MAX_RECONNECT_DELAY = 1

logger = get_logger(__name__, log_file="input_module.log")

class MQTTEventWatcher(EventWatcher):
    def __init__(self,
                 metadata_manager: MetadataManager,
                 start_topics: Optional[List[str]] = None,
                 stop_topics: Optional[List[str]] = None,
                 measurement_topics: Optional[List[str]] = None,
                 error_topics: Optional[List[str]] = None,
                 broker: str = None,
                 port: int = 1883,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 clientid: Optional[str] = None,
                 protocol: Literal["v3", "v5"] = "v3",
                 transport: Literal["tcp", "websockets", "unix"] = "tcp",
                 tls: bool = False,
                 callbacks: Optional[List[Callable]] = None, 
                 error_holder: Optional[ErrorHolder] = None) -> None:

        super().__init__(metadata_manager, callbacks=callbacks, 
                         error_holder=error_holder)

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

        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=clientid,
            protocol=self._protocol,
            transport=transport,
        )

        self.client.on_connect = self.on_connect
        self.client.on_connect_fail = self.on_connect_fail
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        if tls:
            try:
                self.client.tls_set()
                self.client.tls_insecure_set(True)
            except Exception as e:
                raise AdapterBuildError(f"Failed to set up TLS: {e}")

        # topic -> list of events
        self._topic_event_map: dict[str, list[str]] = {}
        self._register_topics(start_topics, metadata_manager.experiment.start)
        self._register_topics(measurement_topics, metadata_manager.experiment.measurement)
        self._register_topics(stop_topics, metadata_manager.experiment.stop)
        self._register_topics(error_topics, metadata_manager.error)


    def _register_topics(self,topics: Optional[List[str]], event: str):
        if topics:
            for topic in topics:
                self._topic_event_map.setdefault(topic, []).append(event)

    def start(self):
        """
        Connects to the MQTT broker and sets a thread looping.
        """
        super().start()
        try:
            if self._username and self._password:
                self.client.username_pw_set(self._username, 
                                            self._password)
            self.client.connect(self._broker, self._port, 60)
            self.client.loop_start()
            time.sleep(3)
            for topic in self._topic_event_map.keys():
                self.subscribe(topic)
                time.sleep(0.1)

        except (socket_error, gaierror, OSError) as e:
            self._handle_exception(
                ClientUnreachableError(
                    f"Error connecting to broker: {self._broker} {e}",
                    output_module=self))

    def stop(self) -> None:
        """
        Disconnect from the MQTT broker and stop the threaded loop.
        """
        try:
            if self.client.is_connected():
                self.client.disconnect()
                time.sleep(0.5)
            self.client.loop_stop()
        except Exception as e:
            self._handle_exception(
                ClientUnreachableError(
                    "Failed to disconnect from broker.", 
                    output_module=self))
            
    def on_message(self, client: mqtt.Client, 
                userdata: Any, msg: mqtt.MQTTMessage) -> None:
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
        full_payload = {"topic": incoming_topic, 
                        "payload": payload}

        for registered_topic, events in self._topic_event_map.items():
            if topic_utilities.is_instance(incoming_topic, 
                                           registered_topic):
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
        metadata: Optional[Any] = None,
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
        if rc != 0:
            error_messages = {
                1: "Unacceptable protocol version",
                2: "Client identifier rejected",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized",
            }
            message = error_messages.get(rc.value, f"Unknown connection error with code {rc}")
            self._handle_exception(
                ClientUnreachableError(
                    f"Connection refused: {message}", output_module=self
                )
            )

    def on_connect_fail(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        rc: int,
        metadata: Optional[Any] = None,
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
        properties: Optional[Any] = None,
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
        if rc != mqtt.MQTT_ERR_SUCCESS:
            reconnect_count, reconnect_delay = 0, FIRST_RECONNECT_DELAY
            while reconnect_count < MAX_RECONNECT_COUNT:
                time.sleep(reconnect_delay)
                try:
                    client.reconnect()
                    return
                except Exception:
                    reconnect_delay = min(
                        reconnect_delay * RECONNECT_RATE, MAX_RECONNECT_DELAY
                    )
                    reconnect_count += 1
            self._handle_exception(
                ClientUnreachableError("Failed to reconnect.", output_module=self)
            )

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