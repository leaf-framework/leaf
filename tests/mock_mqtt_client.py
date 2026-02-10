import json
import re
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage
from paho.mqtt.enums import MQTTErrorCode

from leaf.modules.output_modules.mqtt import MQTT


class MockBioreactorClient(MQTT):
    def __init__(
        self,
        broker_address: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        remove_flush: bool = False,
    ):
        super().__init__(broker_address, port, username=username, password=password, clientid=None)
        self.messages = {}
        self.num_msg = 0
        self.client.on_message = self.on_message
        self._subs = []
        self._remove_flush = remove_flush
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.client.publish("test/topic", "test message")

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: int,
        properties: Any | None = None,
    ) -> None:
        self.flush("test/topic")

    def on_message(self, client: mqtt.Client, userdata: str, msg: MQTTMessage) -> None:
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
            if payload == "":
                if self._remove_flush and topic in self.messages:
                    del self.messages[topic]
                return
            payload = json.loads(payload)
        except UnicodeDecodeError:
            print(f"Non-UTF-8 message payload received. {topic}")
            raise UnicodeDecodeError("UTF-8", msg.payload, 0)
        except json.JSONDecodeError:
            print(f"JSON DECODE ERROR {topic} of {payload}")
            # raise json.JSONDecodeError("JSON Decode Error", msg.payload, 0)

        if topic not in self.messages:
            self.messages[topic] = []
        self.messages[topic].append(payload)
        self.num_msg += 1

    def subscribe(self, topic: str) -> str:
        topic = topic.strip().replace(" ", "")
        topic = re.sub(r"\s+", "", topic)
        self.client.subscribe(topic)
        self._subs.append(topic)
        return topic

    def is_subscribed(self, topic: str) -> bool:
        if topic in self._subs:
            return True
        return False

    def disconnect(self) -> MQTTErrorCode:
        return self.client.disconnect()

    def unsubscribe(self, topic: str) -> str:
        self.client.unsubscribe(topic)
        return topic
