import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.output_modules.file import FILE


class TestFILEOutputModule(unittest.TestCase):
    def setUp(self):
        # Use a real temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.filename = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.filename):
            os.remove(self.filename)

    def test_transmit_creates_file_with_new_topic(self):
        """Test that transmit creates a new file and appends a line"""
        topic = "test_topic"
        data = "test_data"

        file_module = FILE(filename=self.filename)
        result = file_module.transmit(topic, data)

        self.assertTrue(result)
        self.assertTrue(os.path.exists(self.filename))

        # Verify the content
        with open(self.filename) as f:
            line = f.readline().strip()
            parsed = json.loads(line)
            self.assertEqual(parsed, {topic: [data]})

    def test_transmit_appends_data_to_existing_file(self):
        """Test that transmit appends new lines to an existing file"""
        topic1 = "topic1"
        topic2 = "topic2"
        data1 = "data1"
        data2 = "data2"

        file_module = FILE(filename=self.filename)
        file_module.transmit(topic1, data1)
        file_module.transmit(topic2, data2)

        # Verify both lines exist
        with open(self.filename) as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)

            parsed1 = json.loads(lines[0].strip())
            parsed2 = json.loads(lines[1].strip())

            self.assertEqual(parsed1, {topic1: [data1]})
            self.assertEqual(parsed2, {topic2: [data2]})

    def test_transmit_same_topic_multiple_times(self):
        """Test that the same topic can be transmitted multiple times"""
        topic = "sensor_data"
        data1 = {"temp": 20}
        data2 = {"temp": 21}

        file_module = FILE(filename=self.filename)
        file_module.transmit(topic, data1)
        file_module.transmit(topic, data2)

        # Verify both lines exist with the same topic
        with open(self.filename) as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)

            parsed1 = json.loads(lines[0].strip())
            parsed2 = json.loads(lines[1].strip())

            self.assertEqual(parsed1, {topic: [data1]})
            self.assertEqual(parsed2, {topic: [data2]})

    def test_transmit_with_none_data(self):
        """Test that transmitting None returns True without writing"""
        file_module = FILE(filename=self.filename)
        result = file_module.transmit("topic", None)

        self.assertTrue(result)

        # File should be empty (or not exist)
        if os.path.exists(self.filename):
            with open(self.filename) as f:
                content = f.read()
                self.assertEqual(content.strip(), "")

    def test_retrieve_returns_all_data_for_topic(self):
        """Test that retrieve returns all data for a given topic"""
        topic = "test_topic"
        data1 = "data1"
        data2 = "data2"

        file_module = FILE(filename=self.filename)
        file_module.transmit(topic, data1)
        file_module.transmit(topic, data2)

        # Create a second topic that should not be retrieved
        file_module.transmit("other_topic", "data")
        file_module.transmit("other_topic", "data2")

        results = file_module.retrieve(topic)

        self.assertIsNotNone(results)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], data1)
        self.assertEqual(results[1], data2)

        # Retrieve the other topic
        results = file_module.retrieve("other_topic")
        self.assertIsNotNone(results)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], "data")
        self.assertEqual(results[1], "data2")

    def test_retrieve_returns_none_for_nonexistent_topic(self):
        """Test that retrieve returns None when topic doesn't exist"""
        file_module = FILE(filename=self.filename)
        file_module.transmit("other_topic", "data")

        results = file_module.retrieve("nonexistent_topic")

        self.assertIsNone(results)

    def test_retrieve_returns_empty_list_for_nonexistent_file(self):
        """Test that retrieve returns empty list when file doesn't exist"""
        os.remove(self.filename)
        file_module = FILE(filename=self.filename)

        results = file_module.retrieve("any_topic")

        self.assertEqual(results, [])

    def test_pop_removes_first_occurrence(self):
        """Test that pop removes the first line from the file"""
        topic1 = "topic1"
        topic2 = "topic2"
        data1 = "data1"
        data2 = "data2"

        file_module = FILE(filename=self.filename)
        file_module.transmit(topic1, data1)
        file_module.transmit(topic2, data2)

        # Pop without key removes first line
        result = file_module.pop()

        self.assertIsNotNone(result)
        self.assertEqual(result[0], topic1)
        self.assertEqual(result[1], [data1])

        # Verify only second line remains
        with open(self.filename) as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0].strip())
            self.assertEqual(parsed, {topic2: [data2]})

    def test_pop_with_key_removes_specific_topic(self):
        """Test that pop with a key removes the first matching topic"""
        topic1 = "topic1"
        topic2 = "topic2"
        data1 = "data1"
        data2 = "data2"

        file_module = FILE(filename=self.filename)
        file_module.transmit(topic1, data1)
        file_module.transmit(topic2, data2)

        # Pop specific topic
        result = file_module.pop(key=topic2)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], topic2)
        self.assertEqual(result[1], [data2])

        # Verify only first topic remains
        with open(self.filename) as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0].strip())
            self.assertEqual(parsed, {topic1: [data1]})

    def test_pop_returns_none_when_empty(self):
        """Test that pop returns None when file is empty"""
        file_module = FILE(filename=self.filename)
        result = file_module.pop()

        self.assertIsNone(result)

    def test_pop_returns_none_for_nonexistent_key(self):
        """Test that pop returns None when specified key doesn't exist"""
        file_module = FILE(filename=self.filename)
        file_module.transmit("existing_topic", "data")

        result = file_module.pop(key="nonexistent_topic")

        self.assertIsNone(result)

    def test_is_connected_returns_true(self):
        """Test that is_connected always returns True"""
        file_module = FILE(filename=self.filename)
        self.assertTrue(file_module.is_connected())

    def test_compact_json_format(self):
        """Test that transmit uses compact JSON format (no indentation)"""
        topic = "test"
        data = {"key": "value"}

        file_module = FILE(filename=self.filename)
        file_module.transmit(topic, data)

        with open(self.filename) as f:
            line = f.readline()
            # Compact format should not have newlines within the JSON
            self.assertEqual(line.count("\n"), 1)  # Only trailing newline
            # Should use separators without spaces
            self.assertIn('{"test":[{"key":"value"}]}', line)


if __name__ == "__main__":
    unittest.main()
