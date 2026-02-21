import json
import multiprocessing
import os
import threading
import time
import unittest

import pytest
import redis
import yaml

import leaf.start
from leaf.modules.output_modules.mqtt import MQTT
from leaf.utility.logger.logger_utils import get_logger

curr_dir: str = os.path.dirname(os.path.realpath(__file__))


def run_leaf(config):
    logger = get_logger(__name__, log_file="input_module.log")
    logger.info("Starting LEAF process")
    leaf.start.main(["--nogui", "--config", config, "--no-signals"])


class TestKeyDB(unittest.TestCase):
    def setUp(self):
        # Use isolated Redis DB if available, otherwise use default
        db_num = getattr(self, "_redis_db_num", 0)
        self.db = redis.Redis(host="localhost", port=6379, db=db_num)

    def tearDown(self):
        # Clean up Redis after each test
        self.db.flushdb()

    @property
    def logger(self):
        """Simple logger property for tests that need logging."""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(__name__, log_file="input_module.log")
        return self._logger

    def test_set_and_get(self):
        """Test basic Redis set and get operations.

        Verifies that a key-value pair can be stored and retrieved correctly
        from the Redis database.
        """
        # Set a key-value pair and verify that it can be retrieved
        self.db.set("key", "value")
        result = self.db.get("key").decode("utf-8")  # Decode from bytes to string
        self.assertEqual(result, "value")

    def test_delete(self):
        """Test Redis key deletion functionality.

        Verifies that keys can be deleted from Redis and that attempting
        to retrieve a deleted key returns None.
        """
        # Set a key-value pair and then delete it
        self.db.set("key", "value")
        self.db.delete("key")
        result = self.db.get("key")
        self.assertIsNone(result)  # Redis returns None if the key doesn't exist

    def test_flushdb(self):
        """Test Redis database flushing (clearing all data).

        Verifies that flushdb removes all keys from the database,
        making them unavailable for retrieval.
        """
        # Set multiple key-value pairs and flush the database
        self.db.set("key1", "value1")
        self.db.set("key2", "value2")
        self.db.flushdb()

        result1 = self.db.get("key1")
        result2 = self.db.get("key2")

        self.assertIsNone(result1)  # Both keys should be deleted
        self.assertIsNone(result2)

    @pytest.mark.timeout(0)
    def test_leaf(self):
        """Test LEAF application integration with KeyDB output module.

        This test starts the LEAF application with a KeyDB configuration,
        waits for data to be written to KeyDB, and verifies the data structure
        and operations (like list length changes after popping elements).
        """
        config = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "tests", "static_files", "test_config_keydb.yaml"
        )
        # Load configuration from the YAML file
        if not os.path.exists(config):
            raise FileNotFoundError(f"Configuration file {config} not found.")
        with open(config) as file:
            config_data = yaml.safe_load(file)
            print("Configuration loaded:", config_data)

        # Get KEYDB output module configuration
        keydb_config = config_data["OUTPUTS"][0]
        print("KeyDB configuration:", keydb_config)
        host = keydb_config.get("host")
        port = keydb_config.get("port")
        db = keydb_config.get("db")

        print(f"Connecting to KeyDB at {host}:{port}, DB: {db}")
        # Connect to the KeyDB instance
        try:
            keydb_client = redis.Redis(host=host, port=port, db=db)
            # Test the connection
            keydb_client.ping()
            print("Connected to KeyDB successfully")
        except redis.ConnectionError as e:
            print("Failed to connect to KeyDB:", e)
            self.fail("Could not connect to KeyDB")
        except Exception as e:
            print(f"KeyDB ping failed: {e}")
            self.fail(f"KeyDB not responding: {e}")

        # Flush the test database before starting
        keydb_client.flushdb()
        print("Flushed KeyDB test database")

        # Start the leaf application in a separate thread
        thread = threading.Thread(target=run_leaf, args=[config], daemon=True)
        thread.start()
        print("LEAF thread started")

        # Set a timeout to avoid hanging forever
        timeout = 60  # seconds
        start_time = time.time()

        # If thread is killed due to error, we want to know
        while True:
            try:
                # Check timeout
                if time.time() - start_time > timeout:
                    current_keys = sorted(keydb_client.keys("keydb_test_instance*"))
                    self.fail(
                        f"Test timed out after {timeout} seconds. "
                        f"Expected 2 keys but found {len(current_keys)}: {current_keys}"
                    )

                # Check if the thread is still alive
                if not thread.is_alive():
                    current_keys = sorted(keydb_client.keys("keydb_test_instance*"))
                    print(f"LEAF thread has finished unexpectedly. Keys found: {current_keys}")
                    self.fail(
                        f"LEAF thread stopped early. Expected 2 keys but found {len(current_keys)}: {current_keys}"
                    )
                # Obtain data from KeyDB
                keys = sorted(keydb_client.keys("keydb_test_instance*"))
                self.logger.info("Current keys in KeyDB: %s", keys)
                if len(keys) == 2:
                    # Find keys by pattern instead of assuming order
                    details_key = None
                    measurement_key = None
                    for key in keys:
                        if b"/details" in key:
                            details_key = key
                        elif b"/measurement/" in key:
                            measurement_key = key

                    # Assert both expected keys are present
                    assert (
                        details_key
                        == b"keydb_test_instance_institute1/keydb_test_instance_department1/Example/keydb_test_instance/details"
                    )
                    assert (
                        measurement_key
                        == b"keydb_test_instance_institute1/keydb_test_instance_department1/Example/keydb_test_instance/experiment/undefined/measurement/unknown"
                    )
                    self.logger.info("Current keys in KeyDB: %s", keys)
                    # Number of values in the list
                    size_before = keydb_client.llen(details_key)
                    self.logger.info("Number of values in the list: %d", size_before)
                    # Obtain the values for the keys
                    value1 = json.loads(keydb_client.lpop(details_key))
                    self.logger.info("Value for key1: %s", value1)
                    # Number of values in the list
                    size_after = keydb_client.llen(details_key)
                    self.logger.info("Number of values in the list: %d", size_after)
                    assert size_after == size_before - 1
                    break
                # Sleep for a while to avoid busy waiting
                time.sleep(1)
            except KeyboardInterrupt:
                print("Interrupted by user, stopping LEAF")
                break
        # Stop the leaf thread
        thread.join(1)

    # To make this test work you need to disable the ....
    #     signal.signal(signal.SIGINT, signal_handler)
    #     signal.signal(signal.SIGTERM, signal_handler)
    #     sys.excepthook = handle_exception
    # for now...
    @unittest.skip("Complex integration test - needs MQTT message consumption logic fix")
    def test_keydb_switch_to_mqtt(self):
        """Test switching from KeyDB to MQTT output mode with message verification.

        This integration test:
        1. Runs LEAF with KeyDB output to collect messages
        2. Stores all messages from KeyDB
        3. Switches to MQTT mode with KeyDB fallback
        4. Verifies that all previously stored KeyDB messages are sent via MQTT

        This ensures proper failover and message delivery between output modules.
        """
        config = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "tests", "static_files", "test_config_keydb.yaml"
        )

        if not os.path.exists(config):
            raise FileNotFoundError(f"Configuration file {config} not found.")

        # Load configuration from the YAML file
        with open(config) as file:
            config_data = yaml.safe_load(file)
            self.logger.info("Configuration loaded:", config_data)

        # Get KEYDB output module configuration
        keydb_config = config_data["OUTPUTS"][0]
        self.logger.info("KeyDB configuration:", keydb_config)
        host = keydb_config.get("host")
        port = keydb_config.get("port")
        db = keydb_config.get("db")

        keydb_client = redis.Redis(host=host, port=port, db=db)
        # Delete all keys in KeyDB to start fresh
        keydb_client.flushdb()
        self.logger.info("Deleted all keys in KeyDB")

        # Start the LEAF application with KeyDB output module
        self.logger.info("Starting LEAF with KeyDB output module")
        # Start the leaf application in a separate thread
        p = multiprocessing.Process(target=run_leaf, args=(config,))
        p.start()

        self.logger.info(f"Connecting to KeyDB at {host}:{port}, DB: {db}")
        # Connect to the KeyDB instance
        keydb_client = redis.Redis(host=host, port=port, db=db)
        # Wait for the LEAF thread to start and populate KeyDB
        while True:
            # Check if the thread is still alive
            if not p.is_alive():
                self.logger.info("LEAF thread has finished")
                break
            # Obtain data from KeyDB
            while True:
                keys = keydb_client.keys()
                self.logger.info("Current keys in KeyDB: %s", keys)
                if (
                    b"keydb_test_instance_institute1/keydb_test_instance_department1/Example/keydb_test_instance/experiment/undefined/measurement/bioreactor_example"
                    in keys
                    and b"keydb_test_instance_institute1/keydb_test_instance_department1/HelloWorld/keydb_test_instance/details" in keys
                ):
                    self.logger.info("Current keys in KeyDB: %s", keys)
                    # Number of values in the list
                    size_now = keydb_client.llen(
                        "keydb_test_instance_institute1/keydb_test_instance_department1/Example/keydb_test_instance/experiment/undefined/measurement/bioreactor_example"
                    )
                    self.logger.info("Number of values in the list: %d", size_now)
                    if size_now > 5:
                        # Stop the LEAF thread
                        self.logger.info("Stopping LEAF thread due to sufficient data in KeyDB")
                        p.join(1)
                        p.terminate()
                        break
                # Sleep for a while to avoid busy waiting
                time.sleep(1)

        # Check if the LEAF process is still alive by counting the number of messages in KeyDB
        while p.is_alive():
            self.logger.info("Number of messages in KeyDB: %d", keydb_client.llen(keys[0]))
            p.terminate()
            p.join(1)

        # Obtain all messages from KeyDB to check if they are sent over MQTT
        keys = keydb_client.keys()
        message_store = {}
        for key in keys:
            key = key.decode("utf-8")  # Decode bytes to string
            message_store[key] = set()
            self.logger.info("Key: %s", key)
            messages = keydb_client.lrange(key, 0, -1)
            for message in messages:
                self.logger.info("Message: %s", message.decode("utf-8"))
                message_store[key].add(message.decode("utf-8"))

        self.logger.info("Message store: %s", message_store)

        # Start LEAF in MQTT mode
        self.logger.info("Switching LEAF to MQTT mode")

        config = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "tests",
            "static_files",
            "test_config_mqtt_with_keydb_fallback.yaml",
        )

        def on_message_test(client, userdata, msg):
            """Callback function to handle incoming MQTT messages."""
            self.logger.info(f"Received message on topic {msg.topic}: {msg.payload.decode('utf-8')}")
            keys = message_store.keys()
            if msg.topic in keys:
                for m in message_store[msg.topic]:
                    if json.loads(msg.payload.decode("utf-8")) == m:
                        self.logger.info("Message matches stored message, test passed")
                        # Delete the message from message_store
                        message_store[msg.topic].remove(m)
                        self.logger.info(f"Number of remaining messages: {len(message_store[msg.topic])}")
                        if len(message_store[msg.topic]) == 0:
                            self.logger.info("All messages for topic %s have been received", msg.topic)
                            del message_store[msg.topic]
                        break

        output = MQTT("localhost", 1883)
        # output.client.connect("localhost", 1883, 60)
        output.client.subscribe("#")
        output.client.on_message = on_message_test

        # run_leaf(config)

        p = multiprocessing.Process(target=run_leaf, args=(config,))
        p.start()

        # Wait for the thread to finish
        while p.is_alive():
            # self.logger.info(f"Message store: {message_store}")
            if len(message_store) == 0:
                self.logger.info("All messages have been received, stopping LEAF")
                p.terminate()
                p.join(1)
                break
            time.sleep(1)


if __name__ == "__main__":
    unittest.main()
