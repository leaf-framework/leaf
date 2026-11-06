import json
import os
import sys
import time
import unittest
from datetime import datetime
from threading import Thread
from unittest.mock import patch

import yaml
from leafobject import LeafPoint  # pyright: ignore[reportMissingTypeStubs]

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.error_handler.exceptions import InterpreterError
from leaf.modules.input_modules.mqtt_watcher import MQTTEventWatcher
from leaf.modules.output_modules.mqtt import MQTT
from leaf.register.metadata import MetadataManager
from tests.generic_adapter.adapter import GenericDiscreteAdapter
from tests.mock_mqtt_client import MockBioreactorClient

curr_dir: str = os.path.dirname(os.path.realpath(__file__))

with open(curr_dir + "/../../test_config.yaml") as file:
    config = yaml.safe_load(file)

broker = config["OUTPUTS"][0]["broker"]
port = int(config["OUTPUTS"][0]["port"])
try:
    un = config["OUTPUTS"][0]["username"]
    pw = config["OUTPUTS"][0]["password"]
except KeyError:
    un = None
    pw = None


class TestMQTTWatcher(unittest.TestCase):
    def setUp(self):
        self._mock_client = MockBioreactorClient(broker, port, username=un, password=pw)

    def send_messages(self, topic, payload):
        self._mock_client.transmit(topic, payload)
        time.sleep(0.1)

    def test_mqtt_event_watcher_start(self):
        recieved_messages = []

        def mock_start_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        start_topics = [
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/growth_rate_calculating",
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity",
        ]
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            start_topics=start_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_start_process],
        )

        watcher.start()
        payload = {}
        for topic in start_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()
        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.start())
            self.assertIn(data["topic"], start_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_start_partials(self):
        recieved_messages = []

        def mock_start_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        start_topics = ["pioreactor/Worker2-1/#"]
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            start_topics=start_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_start_process],
        )

        watcher.start()
        payload = {}
        transmit_topics = ["pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in transmit_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        non_registered_topics = ["non_reg_suf/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in non_registered_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.start())
            self.assertIn(data["topic"], transmit_topics)
            self.assertNotIn(data["topic"], non_registered_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_measurement(self):
        recieved_messages = []

        def mock_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        measurement_topics = [
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/growth_rate_calculating",
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity",
        ]

        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            measurement_topics=measurement_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_process],
        )

        watcher.start()
        payload = {}
        for topic in measurement_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()
        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.measurement())
            self.assertIn(data["topic"], measurement_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_measurement_partials(self):
        recieved_messages = []

        def mock_measurement_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        measurement_topics = ["pioreactor/Worker2-1/#"]
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            measurement_topics=measurement_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_measurement_process],
        )

        watcher.start()
        payload = {}
        transmit_topics = ["pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in transmit_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        non_registered_topics = ["non_reg_suf/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in non_registered_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.measurement())
            self.assertIn(data["topic"], transmit_topics)
            self.assertNotIn(data["topic"], non_registered_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_stop(self):
        recieved_messages = []

        def mock_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        stop_topics = [
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/growth_rate_calculating",
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity",
        ]

        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            stop_topics=stop_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_process],
        )

        watcher.start()
        payload = {}
        for topic in stop_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()
        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.stop())
            self.assertIn(data["topic"], stop_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_stop_partials(self):
        recieved_messages = []

        def mock_stop_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        stop_topics = ["pioreactor/Worker2-1/#"]
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            stop_topics=stop_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_stop_process],
        )

        watcher.start()
        payload = {}
        transmit_topics = ["pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in transmit_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        non_registered_topics = ["non_reg_suf/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in non_registered_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.stop())
            self.assertIn(data["topic"], transmit_topics)
            self.assertNotIn(data["topic"], non_registered_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_error(self):
        recieved_messages = []

        def mock_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        error_topics = [
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/growth_rate_calculating",
            "pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity",
        ]

        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            error_topics=error_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_process],
        )

        watcher.start()
        payload = {}
        for topic in error_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()
        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.error())
            self.assertIn(data["topic"], error_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_error_partials(self):
        recieved_messages = []

        def mock_error_process(topic, data):
            recieved_messages.append((topic, data))

        metadata_manager = MetadataManager()
        error_topics = ["pioreactor/Worker2-1/#"]
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            error_topics=error_topics,
            port=port,
            username=un,
            password=pw,
            clientid=None,
            callbacks=[mock_error_process],
        )

        watcher.start()
        payload = {}
        transmit_topics = ["pioreactor/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in transmit_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        non_registered_topics = ["non_reg_suf/Worker2-1/LacZ-Slow-Single-KO/intensity"]
        for topic in non_registered_topics:
            mthread = Thread(target=self.send_messages, args=(topic, payload))
            mthread.start()
            mthread.join()

        watcher.stop()
        self.assertTrue(len(recieved_messages) > 0)
        for r in recieved_messages:
            topic, data = r
            self.assertEqual(topic(), metadata_manager.error())
            self.assertIn(data["topic"], transmit_topics)
            self.assertNotIn(data["topic"], non_registered_topics)
            self.assertIn("payload", data)

    def test_mqtt_event_watcher_all_topic_types(self):
        received_events = {"start": [], "measurement": [], "stop": [], "error": []}

        def callback(event, data):
            if event() == metadata_manager.start():
                received_events["start"].append(data)
            elif event() == metadata_manager.measurement():
                received_events["measurement"].append(data)
            elif event() == metadata_manager.stop():
                received_events["stop"].append(data)
            elif event() == metadata_manager.error():
                received_events["error"].append(data)

        metadata_manager = MetadataManager()
        start_topics = ["pioreactor/device1/start"]
        measurement_topics = ["pioreactor/device1/measurement"]
        stop_topics = ["pioreactor/device1/stop"]
        error_topics = ["pioreactor/device1/error"]

        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            start_topics=start_topics,
            measurement_topics=measurement_topics,
            stop_topics=stop_topics,
            error_topics=error_topics,
            port=port,
            username=un,
            password=pw,
            callbacks=[callback],
        )

        watcher.start()
        time.sleep(1)

        topics_and_event_keys = [
            (start_topics[0], "start"),
            (measurement_topics[0], "measurement"),
            (stop_topics[0], "stop"),
            (error_topics[0], "error"),
        ]

        payload = {"some": "data"}
        for topic, _ in topics_and_event_keys:
            self.send_messages(topic, payload)
            time.sleep(0.1)

        watcher.stop()
        for key, topic in zip(received_events.keys(), [t[0] for t in topics_and_event_keys]):
            self.assertTrue(len(received_events[key]) > 0, f"No message received for {key}")
            for msg in received_events[key]:
                self.assertIn("topic", msg)
                self.assertIn("payload", msg)
                self.assertEqual(msg["topic"], topic)

    def test_mqtt_invalid_broker_raises_error(self):
        metadata_manager = MetadataManager()
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker="invalid.broker.address",
            start_topics=["some/topic"],
            port=1883,
            clientid=None,
            callbacks=[],
        )

        with self.assertRaises(Exception):
            watcher.start()

    def test_add_callback_after_init(self):
        messages = []

        def cb(topic, data):
            messages.append((topic, data))

        metadata_manager = MetadataManager()
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            start_topics=["pioreactor/Worker2-1/LacZ-Slow-Single-KO/growth_rate_calculating"],
            port=port,
            username=un,
            password=pw,
            clientid=None,
        )

        watcher.add_callback(cb)
        watcher.start()
        # Resend until one arrives: the subscription may not be in place yet on a slow runner
        deadline = time.time() + 10
        while not messages and time.time() < deadline:
            self.send_messages("pioreactor/Worker2-1/LacZ-Slow-Single-KO/growth_rate_calculating", {})
            time.sleep(0.2)
        watcher.stop()
        self.assertTrue(len(messages) > 0)

    def test_disconnect_logs_warning_for_unexpected_disconnect(self):
        """Test that unexpected disconnect logs a warning (paho handles reconnection)."""
        metadata_manager = MetadataManager()
        watcher = MQTTEventWatcher(
            metadata_manager=metadata_manager,
            broker=broker,
            port=port,
            username=un,
            password=pw,
        )
        # Unexpected disconnect (rc != 0) should just log, paho's loop_start handles reconnection
        with patch("leaf.modules.input_modules.mqtt_watcher.logger") as mock_logger:
            watcher.on_disconnect(watcher.client, None, None, 1)
            mock_logger.warning.assert_called_once()
            self.assertIn("paho will auto-reconnect", mock_logger.warning.call_args[0][0])

    def test_invalid_protocol(self):
        with self.assertRaises(Exception):
            MQTTEventWatcher(
                metadata_manager=MetadataManager(),
                broker=broker,
                port=port,
                protocol="invalid",
            )

    @patch("paho.mqtt.client.Client.tls_set", side_effect=Exception("TLS failed"))
    def test_tls_setup_failure(self, mock_tls):
        with self.assertRaises(Exception) as context:
            MQTTEventWatcher(metadata_manager=MetadataManager(), broker=broker, port=port, tls=True)
        self.assertIn("Failed to set up TLS", str(context.exception))

    def test_is_connected_flag(self):
        watcher = MQTTEventWatcher(
            metadata_manager=MetadataManager(),
            broker=broker,
            port=port,
        )
        with patch.object(watcher.client, "is_connected", return_value=True):
            self.assertTrue(watcher.is_connected())


class MQTTInputMockInterpreter(AbstractInterpreter):
    def __init__(self, error_holder=None):
        super().__init__(error_holder)

    # A note for when you copy this over.
    # You could enable a system where somebody could provide start experiment as a partial like <bla>/<bla>/#
    # Then when any topic is published to, you send the start signal.
    # Just need to consider how this could be done so the interpreter.metadata isnt being called all the time.
    def metadata(self, data):
        # Mock interpreter assumes topic for this piece of equipment follows the structure:
        # <adapter_id>/<Instance_id>/<experiment_id>/.....
        if "topic" not in data:
            excp = InterpreterError("Recieved metadata without original topic.")
            self._handle_exception(excp)
        if "payload" not in data:
            excp = InterpreterError("Recieved metadata without payload.")
            self._handle_exception(excp)

        topic = data["topic"].split("/")
        self.id = topic[2]

        payload = {self.TIMESTAMP_KEY: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self.EXPERIMENT_ID_KEY: self.id}
        try:
            payload.update(json.loads(data["payload"]))
        except json.JSONDecodeError:
            payload["metadata"] = data["payload"]

        return payload

    def measurement(self, data):
        point = LeafPoint()
        if "topic" not in data:
            excp = InterpreterError("Recieved measurement without original topic.")
            self._handle_exception(excp)
        if "payload" not in data:
            excp = InterpreterError("Recieved measurement without payload.")
            self._handle_exception(excp)

        topic = data["topic"].split("/")
        point.set_timestamp(datetime.now())
        point.add_tag("NA", "NA")
        point.set_entity_tag(data["topic"].split("/")[-3])

        experiment_id = topic[-2]
        # Just to show they SHOULD be the same in this case.
        assert experiment_id == self.id
        # To display, two cases (This depends on how the data actually comes out of the equipment).
        try:
            # The LeafPoint measurement in this example is the suffix
            # measurement type (growth_rate for example.)
            # The fields are the k,v values of the payload of the original mqtt messages.
            point.set_measurement(topic[-1])
            point.set_fields(json.loads(data["payload"]))
        except json.JSONDecodeError:
            # Measurement in this example is the experiment_id (LacZ-Slow-Single-KO for example.)
            # Single field where suffix of topic is the key (growth_rate) and value is the single literal payload.
            point.set_measurement(topic[-2])
            point.add_field(topic[-1], data["payload"])
        return point.to_json()


class TestMQTTWatcherInAdapter(unittest.TestCase):
    def setUp(self):
        self._mock_client = MockBioreactorClient(broker, port, username=un, password=pw)

    def test_end_to_end(self):
        # Constants for test config
        instance_id = "TestMQTTWatcherInAdapter_instance_id"
        organisation_id = "TestMQTTWatcherInAdapter_organisation_id"
        department_id = "TestMQTTWatcherInAdapter_department_id"
        experiment_id = "LacZ-Slow-Single-KO"
        sensor_topic_base = f"pioreactor/Worker2-1/{experiment_id}"
        growth_rate_measurement = "growth_rate"
        stop_signal = "interval"
        error_log = "pid_log"

        instance_data = {"instance_id": instance_id, "organisation": organisation_id, "department": department_id}

        # Define topics
        start_topics = [sensor_topic_base]
        measurement_topics = [f"{sensor_topic_base}/{growth_rate_measurement}"]
        stop_topics = [f"{sensor_topic_base}/{stop_signal}"]
        error_topics = [f"{sensor_topic_base}/{error_log}"]

        # Subscribe to mock MQTT output for validation
        self._mock_client.subscribe(f"{organisation_id}/#")
        time.sleep(0.1)

        # Adapter input config
        input_params = {
            "broker": broker,
            "start_topics": start_topics,
            "measurement_topics": measurement_topics,
            "stop_topics": stop_topics,
            "error_topics": error_topics,
            "port": port,
            "username": un,
            "password": pw,
            "clientid": None,
        }

        # Output client
        output = MQTT(broker=broker, port=port, username=un, password=pw, clientid=None)

        # Start adapter
        self._adapter = GenericDiscreteAdapter(
            instance_data, MQTTEventWatcher, input_params, output, MQTTInputMockInterpreter()
        )

        adapter_thread = Thread(target=self._adapter.start)
        adapter_thread.start()

        # Wait for adapter to be fully running
        timeout, wait_interval, waited = 20, 1, 0
        while not self._adapter.is_running():
            time.sleep(wait_interval)
            waited += wait_interval
            if waited >= timeout:
                self.fail("Adapter did not start in time.")

        # Simulate messages
        start_payload = {"sensors": ["EX [nm]", "EM [nm]"]}
        for topic in start_topics:
            self._mock_client.transmit(topic, start_payload)

        measurement_payload = {"EM [nm]": 0.123, "EX [nm]": 0.876}
        for topic in measurement_topics:
            self._mock_client.transmit(topic, measurement_payload)

        stop_payload = {"timestamp": time.time()}
        for topic in stop_topics:
            self._mock_client.transmit(topic, stop_payload)

        time.sleep(1)
        self._adapter.stop()
        adapter_thread.join()

        metadata_manager = self._adapter._metadata_manager
        output_messages = self._mock_client.messages

        # Validate output metadata
        self.assertIn(metadata_manager.details(), output_messages)

        # Validate start message
        start_event = metadata_manager.start()
        self.assertIn(start_event, output_messages)
        for message in output_messages[start_event]:
            self.assertIn("timestamp", message)
            self.assertIn("experiment_id", message)
            self.assertIn("sensors", message)
            self.assertEqual(message["experiment_id"], experiment_id)

        # Validate measurement message
        # The Pioreactor worker is the entity inside the instance, so it is a topic level
        measurement_event = metadata_manager.measurement(entity="Worker2-1", measurement=growth_rate_measurement)
        self.assertIn(measurement_event, output_messages)
        for message in output_messages[measurement_event]:
            self.assertIn("measurement", message)
            self.assertEqual(message["measurement"], growth_rate_measurement)
            self.assertIn("fields", message)
            self.assertEqual(message["fields"], measurement_payload)

        stop_event = metadata_manager.stop()
        self.assertIn(stop_event, output_messages)

    if __name__ == "__main__":
        unittest.main()
