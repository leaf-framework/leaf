import json
import logging
import time
from socket import error as socket_error
from socket import gaierror
from typing import Literal, Union, Optional, Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, LEAFError
from leaf.error_handler.exceptions import ClientUnreachableError
from leaf.error_handler.exceptions import SeverityLevel
from leaf.modules.output_modules.output_module import OutputModule
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="output_module.log")

FIRST_RECONNECT_DELAY = 1
RECONNECT_RATE = 2
MAX_RECONNECT_COUNT = 12
MAX_RECONNECT_DELAY = 1




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
        username: Optional[str] = None,
        password: Optional[str] = None,
        fallback: Optional[OutputModule] = None,
        clientid: Optional[str] = None,
        protocol: Literal["v3", "v5"] = "v3",
        transport: Literal["tcp", "websockets", "unix"] = "tcp",
        tls: bool = False,
        error_holder: Optional[ErrorHolder] = None,
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
        """

        super().__init__(fallback=fallback, error_holder=error_holder)

        if protocol not in ["v3", "v5"]:
            raise AdapterBuildError(f"Unsupported protocol '{protocol}'.")
        self.protocol = mqtt.MQTTv5 if protocol == "v5" else mqtt.MQTTv311

        if transport not in ["tcp", "websockets", "unix"]:
            raise AdapterBuildError(f"Unsupported transport '{transport}'.")

        if not isinstance(broker, str) or not broker:
            raise AdapterBuildError(
                "Broker must be a non-empty string representing the MQTT broker address."
            )
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise AdapterBuildError("Port must be an integer between 1 and 65535.")

        self._client_id: Optional[str] = clientid
        self._broker: str = broker
        self._port: int = port
        self._username: Optional[str] = username
        self._password: Optional[str] = password
        self._tls: bool = tls
        self.messages: dict[str, list[str]] = {}
        self.sending_success: dict[str,bool] = {}
        self._is_reconnect: bool = False

        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=clientid,
            protocol=self.protocol,
            transport=transport,
        )
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
            self.client.connect(self._broker, self._port, 60)
            self.client.loop_start()
        except (socket_error, gaierror, OSError) as e:
            self._handle_exception(
                ClientUnreachableError(
                    f"Error connecting to broker: {e}", output_module=self
                )
            )

    def disconnect(self) -> None:
        """
        Disconnect from the MQTT broker and stop the threaded loop.
        """
        logger.info(f"Disconnecting from MQTT broker {self._broker}")
        if not self.is_enabled():
            logger.warning(
                f"{self.__class__.__name__} - disconnect called with module disabled."
            )
            return
        try:
            if self.client.is_connected():
                self.client.disconnect()
                time.sleep(0.5)
            self.client.loop_stop()
            logger.info("Disconnected from MQTT broker.")
        except Exception as e:
            logger.error(f"Failed to disconnect from MQTT broker: {e}")
            self._handle_exception(
                ClientUnreachableError(
                    "Failed to disconnect from broker.", output_module=self
                )
            )

    def transmit(
        self, topic: str, data: Optional[Union[str, dict]] = None, retain: bool = False
    ) -> bool:
        """
        Publish a message to the MQTT broker on a given topic.

        Args:
            topic (str): The topic to publish the message to.
            data (Optional[Union[str, dict]]): The message payload to be transmitted.
            retain (bool): Whether to retain the message on the broker.

        Returns:
            bool: True if the message was successfully published, False otherwise.
        """
        if not self.is_enabled():
            logger.warning(
                f"{self.__class__.__name__} - transmit called with module disabled."
            )
            # Call the fallback if available
            if self._fallback is not None:
                logger.debug("Calling fallback as module is disabled.")
                return self.fallback(topic, data)
            return False
        # Register the topic in sending_success if not already present
        if topic not in self.sending_success:
            self.sending_success[topic] = False
        # Check if the client is connected before attempting to publish
        if not self.client.is_connected():
            return self.fallback(topic, data)
        if data == "":
            data = {}
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        try:
            result = self.client.publish(
                topic=topic, payload=data, qos=0, retain=retain
            )
        except ValueError:
            msg = f"{topic} contains wildcards, likely required instance data missing"
            exception = ClientUnreachableError(
                msg, output_module=self, severity=SeverityLevel.ERROR
            )
            self._handle_exception(exception)
            return False

        error = self._handle_return_code(result.rc)
        if error is not None:
            self.sending_success[topic] = False
            self._handle_exception(error)
            return self.fallback(topic, data)

        # If successfully published, check if the fallback has data on the topic
        # Only do this once to avoid unnecessary calls
        if not self.sending_success[topic]:
            # To prevent recursion in case the fallback also tries to publish
            self.sending_success[topic] = True
            if self._fallback is not None:
                while True:
                    fallback_result = self._fallback.pop(topic)
                    if fallback_result is not None:
                        fallback_topic, fallback_data = fallback_result
                        logger.info(
                            f"Fallback data found for topic {fallback_topic}, publishing now."
                        )
                        self.transmit(fallback_topic, fallback_data)
                        # Sleep 0.05 seconds to allow the message to be processed
                        time.sleep(0.05)
                    else:
                        logger.debug(
                            f"No fallback data found for topic {topic}, stopping fallback."
                        )
                        break
            # Reset the flag after processing fallback data in case new data arrives later
            self.sending_success[topic] = False

        # Reset global failure counter only after successful transmission AND fallback processing
        OutputModule.reset_failure_count()
        return True

    def flush(self, topic: str) -> None:
        """
        Clear any retained messages on the broker
        by publishing an empty payload.

        Args:
            topic (str): The topic to clear retained messages for.
        """
        if not self.is_enabled():
            logger.warning(
                f"{self.__class__.__name__} - flush called with module disabled."
            )
            return
        try:
            result = self.client.publish(topic=topic, payload=None, qos=0, retain=True)
            error = self._handle_return_code(result.rc)
            if error is not None:
                logger.error(
                    f"Failed to flush retained messages on: {topic} {self._username}@{self._broker}"
                )
                self._handle_exception(error)
                return self.fallback(topic, None)
        except ValueError:
            msg = f"{topic} contains wildcards, likely required instance data missing"
            exception = ClientUnreachableError(
                msg, output_module=self, severity=SeverityLevel.CRITICAL
            )
            self._handle_exception(exception)

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
        if not self.is_enabled():
            logger.warning(
                f"{self.__class__.__name__} - on_connect called with module disabled."
            )
            return
        if self._is_reconnect:
            logger.info(f"Reconnected to broker {self._username}@{self._broker}")
            self._is_reconnect = False
            # Fallback data will be sent in transmit method
        else:
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
            self._handle_exception(
                ClientUnreachableError(
                    f"Connection refused: {message}", output_module=self
                )
            )

    def on_connect_fail(
        self,
        client: mqtt.Client,
        userdata: Any,
    ) -> None:
        """
        Callback for when the client fails to connect to the broker.

        Args:
            client (mqtt.Client): The MQTT client instance.
            userdata (Any): The private user data as set in
                            Client() or userdata_set().
        """
        logger.error("Connection failed")
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
        logger.info(f"Disconnected from broker {self._username}@{self._broker}")
        global MAX_RECONNECT_COUNT
        if not self.is_enabled():
            logger.warning(
                f"{self.__class__.__name__} - disconnect called with module disabled."
            )
            return
        
        if rc != mqtt.MQTT_ERR_SUCCESS:
            reconnect_count, reconnect_delay = 0, FIRST_RECONNECT_DELAY
            while reconnect_count < MAX_RECONNECT_COUNT:
                time.sleep(reconnect_delay)
                try:
                    self._is_reconnect = True
                    client.reconnect()
                    return
                except Exception as e:
                    logger.error(f"Reconnect attempt {reconnect_count + 1} failed: {e}")

                    reconnect_delay = min(
                        reconnect_delay * RECONNECT_RATE, MAX_RECONNECT_DELAY
                    )
                    reconnect_count += 1
            self._handle_exception(
                ClientUnreachableError("Failed to reconnect.", output_module=self)
            )


    def on_log(
        self, client: mqtt.Client, userdata: Any, paho_log_level: int, message: str
    ) -> None:
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

    def on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
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

    def reset_messages(self) -> None:
        """
        Reset the stored messages to an empty dictionary.
        """
        self.messages = {}

    def subscribe(self, topic: str) -> str:
        """
        Subscribe to a topic on the MQTT broker.

        Args:
            topic (str): The topic to subscribe to.

        Returns:
            str: The subscribed topic.
        """
        logger.info(f"Subscribing to {topic}")
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

    def pop(self, key: Optional[str] = None) -> Any:
        """
        Retrieve and remove a stored message from the fallback.

        MQTT does not buffer messages locally, so this delegates to the fallback
        module (e.g., KeyDB or FILE) to retrieve buffered messages.

        Args:
            key (Optional[str]): A key for which to pop data. Defaults to None.

        Returns:
            Any: Retrieved message tuple (topic, message) or None if no messages.
        """
        if self._fallback is not None:
            return self._fallback.pop(key)
        return None

    def _handle_return_code(self, return_code: int) -> Optional[ClientUnreachableError]:
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

        return ClientUnreachableError(
            message, output_module=self, severity=SeverityLevel.INFO
        )
