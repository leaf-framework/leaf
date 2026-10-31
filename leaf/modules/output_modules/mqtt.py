import json
import re
import threading
import time
from collections.abc import Callable
from socket import gaierror
from typing import Any, Literal, cast

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, ClientUnreachableError, LEAFError, SeverityLevel
from leaf.modules.output_modules.output_module import OutputModule
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="output_module.log")

# '+' and '#' are MQTT wildcard characters and NUL is disallowed outright;
# paho rejects any of these in a topic passed to publish(). Equipment tag
# names occasionally contain them literally (e.g. an OPC tag named
# "R1_Project#"), so strip them rather than treating it as a broker error.
_ILLEGAL_TOPIC_CHARS = re.compile(r"[+#\x00]")


class MQTT(OutputModule):
    """
    Handles output via the MQTT protocol. Inherits from the abstract
    OutputModule class and is responsible for publishing data to an
    MQTT broker. If transmission fails, it can use a fallback
    OutputModule if one is provided.
    Adapter establishes a connection to the MQTT broker, manages
    reconnections, and handles message publishing. It supports both
    TCP and WebSocket transports, with optional TLS encryption
    for secure communication.
    """

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        fallback: OutputModule | None = None,
        clientid: str | None = None,
        protocol: Literal["v3", "v5"] = "v3",
        transport: Literal["tcp", "websockets", "unix"] = "tcp",
        tls: bool = False,
        error_holder: ErrorHolder | None = None,
        name: str | None = None,
        # Heartbeat
        heartbeat_interval: float = 300.0,
        # Removed options, still accepted so existing configs keep loading.
        heartbeat_topic: str | None = None,
        heartbeat_payload: str | dict | None = None,
    ) -> None:
        """
        Initialise the MQTT adapter with broker details,
        authentication, and optional fallback.

        Args:
            broker (str): The address of the MQTT broker.
            port (int): The port number (default is 1883).
            username (Optional[str]): Optional username for authentication.
            password (Optional[str]): Optional password for authentication.
            fallback (Optional[OutputModule]): Another OutputModule to use if the MQTT transmission fails.
            clientid (Optional[str]): Optional client ID to use for the MQTT connection.
            protocol (Literal["v3", "v5"]): MQTT protocol version ("v3" for MQTTv3.1.1, "v5" for MQTTv5).
            transport (Literal['tcp', 'websockets', 'unix']): The transport method, either TCP, WebSockets, or Unix socket.
            tls (bool): Boolean flag to enable or disable TLS encryption.
            error_holder (Optional[ErrorHolder]): An instance of ErrorHolder for tracking errors.
            heartbeat_interval (float): Seconds between heartbeat publishes. Defaults to 300.
                Set to 0 to disable. Each equipment instance gets its own heartbeat on
                <root>/<organisation>/<department>/<adapter_id>/<instance_id>/heartbeat.
                The payload is always ``{"status": "alive", "interval": <seconds>,
                "timestamp": <epoch>, "datetime": <datetime>}``.
            heartbeat_topic, heartbeat_payload: Removed; ignored with a warning.
        """

        super().__init__(fallback=fallback, error_holder=error_holder, name=name)

        if not self._name:
            self._name = f"MQTT({broker}:{port})"

        if protocol not in ["v3", "v5"]:
            raise AdapterBuildError(f"Unsupported protocol '{protocol}'.")
        self.protocol = mqtt.MQTTv5 if protocol == "v5" else mqtt.MQTTv311

        if transport not in ["tcp", "websockets", "unix"]:
            raise AdapterBuildError(f"Unsupported transport '{transport}'.")

        if not isinstance(broker, str) or not broker:
            raise AdapterBuildError("Broker must be a non-empty string representing the MQTT broker address.")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise AdapterBuildError("Port must be an integer between 1 and 65535.")

        self._client_id: str | None = clientid
        self._broker: str = broker
        self._port: int = port
        self._username: str | None = username
        self._password: str | None = password
        self._tls: bool = tls
        self.messages: dict[str, list[str]] = {}
        self.sending_success: dict[str, bool] = {}
        self._sanitized_topic_warned: set[str] = set()
        # Topics with a callback; kept so they are resubscribed after a reconnect (clean session).
        self._subscriptions: dict[str, Callable[[str, str], None]] = {}
        # paho's connect() returns once the socket is open and the CONNECT
        # packet is sent, but the broker's CONNACK (which is what actually
        # flips is_connected() to True) is only processed once loop_start()'s
        # network thread picks it up. Without waiting for it, a transmit()
        # fired immediately after construction - e.g. an adapter's synthetic
        # "start" message - can race that handshake and see is_connected()
        # still False, tripping into the fallback path unnecessarily.
        self._connected_event: threading.Event = threading.Event()

        # One output module is shared by all equipment instances, so each
        # adapter registers its own heartbeat topic via on_adapter_ready.
        self._heartbeat_topics: set[str] = set()
        self._heartbeat_lock: threading.Lock = threading.Lock()
        self._heartbeat_interval: float = heartbeat_interval
        if heartbeat_topic is not None or heartbeat_payload is not None:
            logger.warning(
                "heartbeat_topic and heartbeat_payload are no longer supported and are ignored; "
                "each instance publishes on its own .../<instance_id>/heartbeat topic."
            )
        self._heartbeat_stop: threading.Event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

        client_kwargs: dict[str, Any] = {
            "callback_api_version": CallbackAPIVersion.VERSION2,
            "client_id": clientid,
            "protocol": self.protocol,
            "transport": transport,
        }
        if self.protocol != mqtt.MQTTv5:
            client_kwargs["clean_session"] = True

        self.client = mqtt.Client(**client_kwargs)
        self.client.on_connect = self.on_connect

        self.client.on_connect_fail = self.on_connect_fail
        self.client.on_disconnect = self.on_disconnect
        self.client.on_log = self.on_log
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

        self.connect()

    def connect(self) -> None:
        """
        Connects to the MQTT broker and sets a thread looping.
        """
        logger.info(f"Connecting to MQTT broker {self._broker}")
        try:
            if self._username and self._password:
                self.client.username_pw_set(self._username, self._password)
            self.client.reconnect_delay_set(min_delay=1, max_delay=60)
            self._connected_event.clear()
            self.client.connect(self._broker, self._port, 20)
            self.client.loop_start()
            if self._heartbeat_interval > 0:
                self._start_heartbeat()
        except (gaierror, OSError) as e:
            self._handle_exception(ClientUnreachableError(f"Error connecting to broker: {e}", output_module=self))

    def disconnect(self) -> None:
        """
        Disconnect from the MQTT broker and stop the threaded loop.
        """
        logger.info(f"Disconnecting from MQTT broker {self._broker}")
        if not self.is_enabled():
            logger.warning(f"{self.__class__.__name__} - disconnect called with module disabled.")
            return
        self._stop_heartbeat()
        try:
            if self.client.is_connected():
                self.client.disconnect()
                time.sleep(0.5)
            self.client.loop_stop()
            logger.info("Disconnected from MQTT broker.")
        except Exception as e:
            logger.error(f"Failed to disconnect from MQTT broker: {e}")
            self._handle_exception(ClientUnreachableError("Failed to disconnect from broker.", output_module=self))

    def _sanitize_topic(self, topic: str) -> str:
        """
        Strip MQTT-illegal characters ('+', '#', NUL) out of topic segments
        that mix them with other characters (e.g. an equipment tag literally
        named "R1_Project#"). A segment that is *entirely* '+' or '#' is left
        untouched: that's topic_utilities' placeholder for a required field
        that wasn't filled in (see render_template), and publishing it should
        keep failing loudly - paho rejects it as a wildcard - rather than
        silently going out under a blank segment.

        Logs a warning the first time a given raw topic is seen with such
        characters; silent on subsequent calls for that topic.
        """
        sanitized = "/".join(
            part if part in ("+", "#") else _ILLEGAL_TOPIC_CHARS.sub("", part) for part in topic.split("/")
        )
        if sanitized != topic and topic not in self._sanitized_topic_warned:
            self._sanitized_topic_warned.add(topic)
            logger.warning(f"Topic '{topic}' contains MQTT-illegal characters; publishing as '{sanitized}' instead.")
        return sanitized

    def transmit(
        self, topic: str, data: str | dict | None = None, retain: bool = False, use_fallback: bool = True
    ) -> bool:
        """
        Publish a message to the MQTT broker on a given topic.

        Args:
            topic (str): The topic to publish the message to.
            data (Optional[Union[str, dict]]): The message payload to be transmitted.
            retain (bool): Whether to retain the message on the broker.
            use_fallback (bool): Whether a failed publish should be handed to the
                fallback module. Set to False for messages that are only meaningful
                live (e.g. the heartbeat), so they are dropped rather than buffered
                and replayed later.

        Returns:
            bool: True if the message was successfully published, False otherwise.
        """
        topic = self._sanitize_topic(topic)
        if not self.is_enabled():
            logger.warning(f"{self.__class__.__name__} - transmit called with module disabled.")
            # Call the fallback if available
            if use_fallback and self._fallback is not None:
                logger.debug("Calling fallback as module is disabled.")
                return self.fallback(topic, data)
            return False
        # Register the topic in sending_success if not already present
        if topic not in self.sending_success:
            self.sending_success[topic] = False
        # Check if the client is connected before attempting to publish.
        # A short bounded wait here (rather than failing over immediately)
        # covers the common startup race: connect() returns as soon as the
        # CONNECT packet is sent, but the broker's CONNACK - which is what
        # actually flips is_connected() to True - is only processed once
        # loop_start()'s network thread picks it up moments later. A
        # transmit() fired right after construction (e.g. an adapter's
        # synthetic "start" message) can otherwise lose that race every time.
        if not self.client.is_connected():
            if not self._connected_event.wait(timeout=3) or not self.client.is_connected():
                if not use_fallback:
                    return False
                return self.fallback(topic, data)
        if data == "":
            data = {}
        # The topic store keeps the dict, which the Monitoring plot reads points from
        message = cast(object, data)
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        try:
            result = self.client.publish(topic=topic, payload=data, qos=0, retain=retain)
        except ValueError as e:
            msg = f"Cannot publish to topic '{topic}': {e}"
            exception = ClientUnreachableError(msg, output_module=self, severity=SeverityLevel.WARNING)
            self._handle_exception(exception)
            return False

        error = self._handle_return_code(result.rc)
        if error is not None:
            self.sending_success[topic] = False
            self._handle_exception(error)
            if not use_fallback:
                return False
            return self.fallback(topic, data)

        # If successfully published, check if the fallback has data on the topic
        # Only do this once to avoid unnecessary calls
        if not self.sending_success[topic]:
            # To prevent recursion in case the fallback also tries to publish
            self.sending_success[topic] = True
            if use_fallback and self._fallback is not None:
                while True:
                    fallback_result = self._fallback.pop(topic)
                    if fallback_result is not None:
                        fallback_topic, fallback_data = fallback_result
                        logger.info(f"Fallback data found for topic {fallback_topic}, publishing now.")
                        self.transmit(fallback_topic, fallback_data)
                        # Sleep 0.05 seconds to allow the message to be processed
                        time.sleep(0.05)
                    else:
                        logger.debug(f"No fallback data found for topic {topic}, stopping fallback.")
                        break
            # Reset the flag after processing fallback data in case new data arrives later
            self.sending_success[topic] = False

        # Reset global failure counter only after successful transmission AND fallback processing
        OutputModule.reset_failure_count()

        self.store_latest(topic, message)

        # Transmit to parallel outputs (best-effort, failures don't affect primary result)
        self.transmit_to_parallels(topic, data)

        return True

    def flush(self, topic: str) -> None:
        """
        Clear any retained messages on the broker
        by publishing an empty payload.

        Args:
            topic (str): The topic to clear retained messages for.
        """
        if not self.is_enabled():
            logger.warning(f"{self.__class__.__name__} - flush called with module disabled.")
            return
        try:
            result = self.client.publish(topic=topic, payload=None, qos=0, retain=True)
            error = self._handle_return_code(result.rc)
            if error is not None:
                logger.error(f"Failed to flush retained messages on: {topic} {self._username}@{self._broker}")
                self._handle_exception(error)
                return self.fallback(topic, None)
        except ValueError:
            msg = f"{topic} contains wildcards, likely required instance data missing"
            exception = ClientUnreachableError(msg, output_module=self, severity=SeverityLevel.CRITICAL)
            self._handle_exception(exception)

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
        if not self.is_enabled():
            logger.warning(f"{self.__class__.__name__} - on_connect called with module disabled.")
            return
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

        for topic in list(self._subscriptions):
            self.client.subscribe(topic)
        self._connected_event.set()

    def on_connect_fail(
        self,
        client: mqtt.Client,
        userdata: Any,
    ) -> None:
        """
        Callback for when the client fails to connect to the broker.
        Only logs — must not raise, as this runs on paho's network thread
        and an unhandled exception would kill the reconnect loop.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
        """
        logger.warning(f"Connection to {self._broker}:{self._port} failed, paho will retry")

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
        self._connected_event.clear()
        if not self.is_enabled():
            logger.warning(f"{self.__class__.__name__} - disconnect called with module disabled.")
            return

        if rc != mqtt.MQTT_ERR_SUCCESS:
            # paho's loop_start() handles automatic reconnection
            logger.warning(f"Unexpected disconnect (rc={rc}), paho will auto-reconnect")

    def on_log(self, client: mqtt.Client, userdata: Any, paho_log_level: int, message: str) -> None:
        """
        Callback for logging MQTT client activity.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
            paho_log_level (int): The log level set for the client.
            message (str): The log message.
        """
        logger.debug(f"{paho_log_level} : {message}")

    def is_connected(self) -> bool:
        """
        Check if the MQTT client is connected.

        Returns:
            bool: True if the client is connected, False otherwise.
        """
        connected = self.client.is_connected()
        logger.debug(f"{self.__class__.__name__} - is_connected: {connected}")
        return connected

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
        if topic not in self.messages:
            self.messages[topic] = []
        self.messages[topic].append(payload)
        callback = self._subscriptions.get(topic)
        if callback is not None:
            callback(topic, payload)

    def reset_messages(self) -> None:
        """
        Reset the stored messages to an empty dictionary.
        """
        self.messages = {}

    def subscribe(self, topic: str, callback: Callable[[str, str], None] | None = None) -> str:
        """
        Subscribe to a topic on the MQTT broker.

        Args:
            topic (str): The topic to subscribe to.
            callback (Optional[Callable]): Called with (topic, payload) for each message on this exact topic.

        Returns:
            str: The subscribed topic.
        """
        logger.info(f"Subscribing to {topic}")
        if callback is not None:
            self._subscriptions[topic] = callback
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
        logger.info(f"Unsubscribing from {topic}")
        self._subscriptions.pop(topic, None)
        self.client.unsubscribe(topic)
        return topic

    def enable(self) -> bool:
        """
        Reenable output transmission.

        Returns:
            bool: True if successfully enabled, False otherwise.
        """
        logger.info(f"{self.__class__.__name__} - enabled")
        return super().enable()

    def disable(self) -> bool:
        """
        Stop output transmission.

        Returns:
            bool: True if successfully disabled, False otherwise.
        """
        logger.info(f"{self.__class__.__name__} - disabled")
        return super().disable()

    def pop(self, key: str | None = None) -> Any:
        """
        Retrieve and remove a stored message from the fallback.

        MQTT does not buffer messages locally, so this delegates to the fallback
        module (e.g., SQL or FILE) to retrieve buffered messages.

        Args:
            key (Optional[str]): A key for which to pop data. Defaults to None.

        Returns:
            Any: Retrieved message tuple (topic, message) or None if no messages.
        """
        if self._fallback is not None:
            return self._fallback.pop(key)
        return None

    def _start_heartbeat(self) -> None:
        """Start the background heartbeat thread."""
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"HeartbeatThread-{self._name}", daemon=True
        )
        self._heartbeat_thread.start()
        logger.info(f"Heartbeat started every {self._heartbeat_interval}s")

    def _stop_heartbeat(self) -> None:
        """Signal the heartbeat thread to stop and wait for it to exit."""
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            self._heartbeat_stop.set()
            self._heartbeat_thread.join(timeout=self._heartbeat_interval + 1)
            self._heartbeat_thread = None
            logger.info("Heartbeat stopped.")

    def on_adapter_ready(self, metadata_manager: Any) -> None:
        """Register the instance's heartbeat topic and publish a first beat right away."""
        topic = metadata_manager.heartbeat()
        with self._heartbeat_lock:
            self._heartbeat_topics.add(topic)
        self._publish_heartbeat(topic)

    def on_adapter_stop(self, metadata_manager: Any) -> None:
        """Unregister the instance's heartbeat topic and mark it as stopped."""
        topic = metadata_manager.heartbeat()
        with self._heartbeat_lock:
            self._heartbeat_topics.discard(topic)
        self._publish_heartbeat(topic, "stopped")

    def _publish_heartbeat(self, topic: str, status: str = "alive") -> None:
        """Publish a single heartbeat, never raising."""
        payload = {
            "status": status,
            # Lets consumers judge staleness without knowing the config.
            "interval": self._heartbeat_interval,
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        logger.debug(f"Publishing heartbeat to '{topic}': {payload}")
        try:
            # use_fallback=False: a heartbeat is only meaningful live, so a
            # failed publish is dropped rather than buffered in the fallback
            # and replayed as a stale "alive" once the broker is back.
            self.transmit(topic, payload, retain=True, use_fallback=False)
        except LEAFError as e:
            # Must not propagate - an unhandled exception in the heartbeat thread
            # would silently kill it and stop all future heartbeats.
            logger.debug(f"Heartbeat publish failed, will retry next interval: {e}")

    def _heartbeat_loop(self) -> None:
        """Publish a heartbeat for every registered instance at regular intervals until stopped."""
        while not self._heartbeat_stop.wait(self._heartbeat_interval):
            with self._heartbeat_lock:
                topics = list(self._heartbeat_topics)
            for topic in topics:
                self._publish_heartbeat(topic)

    def _handle_return_code(self, return_code: int) -> ClientUnreachableError | None:
        """
        Handle MQTT return codes.

        Args:
            return_code (int): The return code to handle.

        Returns:
            Optional[ClientUnreachableError]: An error if one occurred, None otherwise.
        """
        if return_code == mqtt.MQTT_ERR_SUCCESS:
            return None
        message = {
            mqtt.MQTT_ERR_NO_CONN: "Can't connect to broker",
            mqtt.MQTT_ERR_QUEUE_SIZE: "Message queue size limit reached",
        }.get(return_code, f"Unknown error with return code {return_code}")

        return ClientUnreachableError(message, output_module=self, severity=SeverityLevel.INFO)
