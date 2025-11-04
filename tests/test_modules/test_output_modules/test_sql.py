import sys
import os
import unittest
import sqlite3
import uuid
import tempfile

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.output_modules.sql import SQL


class TestSQLOutputModule(unittest.TestCase):

    def setUp(self):
        # Create a temporary database file for testing
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.database = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        # Clean up the test database
        if os.path.exists(self.database):
            os.remove(self.database)

    def test_initialize_database_creates_table(self):
        """Test that initializing SQL creates the messages table"""
        sql_module = SQL(database=self.database)

        # Verify table exists
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        result = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'messages')

    def test_transmit_inserts_new_message(self):
        """Test that transmit inserts a new message into the database"""
        topic = "test_topic"
        data = {"key": "value"}

        sql_module = SQL(database=self.database)
        result = sql_module.transmit(topic, data)

        self.assertTrue(result)

        # Verify data was inserted
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute('SELECT topic, data FROM messages WHERE topic = ?', (topic,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], topic)
        self.assertIn('"key"', row[1])
        self.assertIn('"value"', row[1])

    def test_transmit_multiple_messages_same_topic(self):
        """Test that multiple messages can be stored for the same topic"""
        topic = "sensors"
        data1 = {"temp": 20}
        data2 = {"temp": 21}

        sql_module = SQL(database=self.database)
        sql_module.transmit(topic, data1)
        sql_module.transmit(topic, data2)

        # Verify both messages exist
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages WHERE topic = ?', (topic,))
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 2)

    def test_retrieve_pops_one_message_at_a_time(self):
        """Test that retrieve pops and returns one message at a time"""
        topic = "test_topic"
        data1 = {"msg": "first"}
        data2 = {"msg": "second"}

        sql_module = SQL(database=self.database)
        sql_module.transmit(topic, data1)
        sql_module.transmit(topic, data2)

        # First retrieve should get first message and delete it
        result1 = sql_module.retrieve(topic)
        self.assertIsNotNone(result1)
        self.assertEqual(result1[0], topic)
        self.assertEqual(result1[1], data1)

        # Second retrieve should get second message and delete it
        result2 = sql_module.retrieve(topic)
        self.assertIsNotNone(result2)
        self.assertEqual(result2[0], topic)
        self.assertEqual(result2[1], data2)

        # Third retrieve should return None (no more messages)
        result3 = sql_module.retrieve(topic)
        self.assertIsNone(result3)

    def test_retrieve_returns_none_for_nonexistent_topic(self):
        """Test that retrieve returns None when topic doesn't exist"""
        sql_module = SQL(database=self.database)
        results = sql_module.retrieve("nonexistent_topic")

        self.assertIsNone(results)

    def test_pop_removes_first_message(self):
        """Test that pop removes and returns the first message"""
        topic = "test_topic"
        data = {"key": "value"}

        sql_module = SQL(database=self.database)
        sql_module.transmit(topic, data)

        popped = sql_module.pop()

        self.assertIsNotNone(popped)
        self.assertEqual(popped[0], topic)
        self.assertEqual(popped[1], data)

        # Verify message was removed
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages')
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 0)

    def test_pop_with_key_removes_specific_topic(self):
        """Test that pop with a key removes the first message of that topic"""
        topic1 = "topic1"
        topic2 = "topic2"
        data1 = {"msg": "first"}
        data2 = {"msg": "second"}

        sql_module = SQL(database=self.database)
        sql_module.transmit(topic1, data1)
        sql_module.transmit(topic2, data2)

        popped = sql_module.pop(key=topic2)

        self.assertIsNotNone(popped)
        self.assertEqual(popped[0], topic2)
        self.assertEqual(popped[1], data2)

        # Verify only topic2 message was removed
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages WHERE topic = ?', (topic1,))
        count1 = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM messages WHERE topic = ?', (topic2,))
        count2 = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count1, 1)  # topic1 still exists
        self.assertEqual(count2, 0)  # topic2 was removed

    def test_pop_returns_none_when_empty(self):
        """Test that pop returns None when database is empty"""
        sql_module = SQL(database=self.database)
        result = sql_module.pop()

        self.assertIsNone(result)

    def test_pop_returns_none_for_nonexistent_key(self):
        """Test that pop returns None when specified key doesn't exist"""
        sql_module = SQL(database=self.database)
        sql_module.transmit("existing_topic", {"data": "value"})

        result = sql_module.pop(key="nonexistent_topic")

        self.assertIsNone(result)

    def test_is_connected_returns_true(self):
        """Test that is_connected always returns True for SQLite"""
        sql_module = SQL(database=self.database)
        self.assertTrue(sql_module.is_connected())

    def test_transmit_with_none_data_returns_true(self):
        """Test that transmitting None data returns True without inserting"""
        sql_module = SQL(database=self.database)
        result = sql_module.transmit("test_topic", None)

        self.assertTrue(result)

        # Verify nothing was inserted
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages')
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 0)

    def test_concurrent_writes_are_safe(self):
        """Test that multiple sequential writes don't cause data loss"""
        sql_module = SQL(database=self.database)
        topic = "concurrent_test"

        # Simulate rapid writes
        for i in range(100):
            sql_module.transmit(topic, {"count": i})

        # Verify all messages were stored by counting in DB
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages WHERE topic = ?', (topic,))
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 100)

        # Also verify we can retrieve all of them one by one
        retrieved_count = 0
        while True:
            result = sql_module.retrieve(topic)
            if result is None:
                break
            retrieved_count += 1

        self.assertEqual(retrieved_count, 100)


if __name__ == "__main__":
    unittest.main()