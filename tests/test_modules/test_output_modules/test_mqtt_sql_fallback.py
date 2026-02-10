import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from unittest.mock import MagicMock, Mock, patch

from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.sql import SQL


class TestMQTTSQLFallback(unittest.TestCase):
    """
    Test MQTT module with SQL fallback to ensure messages are properly
    deleted from SQL after successful MQTT transmission.
    """

    def setUp(self):
        # Create a temporary database file for testing
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.database = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        # Clean up the test database
        if os.path.exists(self.database):
            os.remove(self.database)

    @patch("paho.mqtt.client.Client")
    def test_fallback_messages_are_deleted_after_successful_transmission(self, mock_mqtt_client_class):
        """
        Test that messages stored in SQL fallback are deleted after
        successful MQTT transmission when connection is restored.
        """
        # Create SQL fallback
        sql_fallback = SQL(filename=self.database)

        # Mock MQTT client
        mock_client = MagicMock()
        mock_mqtt_client_class.return_value = mock_client

        # First, simulate MQTT being disconnected
        mock_client.is_connected.return_value = False

        # Create MQTT with SQL fallback
        mqtt_output = MQTT(broker="localhost", port=1883, fallback=sql_fallback, clientid="test_client")

        # Try to transmit while disconnected - should go to SQL fallback
        topic = "test/topic"
        data1 = {"msg": "first"}
        data2 = {"msg": "second"}
        data3 = {"msg": "third"}

        mqtt_output.transmit(topic, data1)
        mqtt_output.transmit(topic, data2)
        mqtt_output.transmit(topic, data3)

        # Verify messages are in SQL
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count_before = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count_before, 3, "All 3 messages should be in SQL fallback")

        # Now simulate MQTT reconnection
        mock_client.is_connected.return_value = True
        mock_publish_result = Mock()
        mock_publish_result.rc = 0  # MQTT_ERR_SUCCESS
        mock_client.publish.return_value = mock_publish_result

        # Transmit a new message - this should trigger fallback processing
        new_data = {"msg": "fourth"}
        mqtt_output.transmit(topic, new_data)

        # Verify all fallback messages were transmitted via MQTT
        # Should have 4 publish calls: 3 from fallback + 1 new message
        self.assertEqual(mock_client.publish.call_count, 4)

        # Verify SQL database is now empty for this topic
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count_after = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count_after, 0, "SQL should be empty after successful MQTT transmission")

    @patch("paho.mqtt.client.Client")
    def test_fallback_retrieves_one_message_at_a_time(self, mock_mqtt_client_class):
        """
        Test that fallback retrieve() pops one message at a time,
        not all messages at once.
        """
        # Create SQL fallback with test messages
        sql_fallback = SQL(filename=self.database)
        topic = "test/topic"
        sql_fallback.transmit(topic, {"msg": "first"})
        sql_fallback.transmit(topic, {"msg": "second"})

        # Verify both messages are in DB
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

        # Retrieve first message - should return tuple and delete it
        result1 = sql_fallback.retrieve(topic)
        self.assertIsNotNone(result1)
        self.assertIsInstance(result1, tuple)
        self.assertEqual(len(result1), 2)
        self.assertEqual(result1[0], topic)
        self.assertEqual(result1[1], {"msg": "first"})

        # Verify only 1 message left
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

        # Retrieve second message
        result2 = sql_fallback.retrieve(topic)
        self.assertIsNotNone(result2)
        self.assertEqual(result2[1], {"msg": "second"})

        # Verify DB is empty
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

        # Third retrieve should return None
        result3 = sql_fallback.retrieve(topic)
        self.assertIsNone(result3)


if __name__ == "__main__":
    unittest.main()
