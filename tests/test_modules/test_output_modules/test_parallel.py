import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.output_modules.file import FILE
from leaf.modules.output_modules.sql import SQL


class TestParallelOutputModules(unittest.TestCase):
    def setUp(self):
        # Create temporary files for FILE modules
        self.temp_file1 = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.filename1 = self.temp_file1.name
        self.temp_file1.close()

        self.temp_file2 = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.filename2 = self.temp_file2.name
        self.temp_file2.close()

        # Create temporary database for SQL module
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.database = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        for f in [self.filename1, self.filename2, self.database]:
            if os.path.exists(f):
                os.remove(f)

    def test_file_with_sql_parallel(self):
        """Test that transmitting to FILE also sends to SQL parallel."""
        topic = "test_topic"
        data = {"key": "value"}

        file_module = FILE(filename=self.filename1)
        sql_module = SQL(filename=self.database)

        file_module.add_parallel(sql_module)

        result = file_module.transmit(topic, data)

        self.assertTrue(result)

        # Verify data in primary FILE
        with open(self.filename1) as f:
            line = f.readline().strip()
            parsed = json.loads(line)
            self.assertEqual(parsed, {topic: [data]})

        # Verify data also in parallel SQL
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT topic, data FROM messages WHERE topic = ?", (topic,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], topic)

    def test_sql_with_file_parallel(self):
        """Test that transmitting to SQL also sends to FILE parallel."""
        topic = "sensor_data"
        data = {"temp": 22.5}

        sql_module = SQL(filename=self.database)
        file_module = FILE(filename=self.filename1)

        sql_module.add_parallel(file_module)

        result = sql_module.transmit(topic, data)

        self.assertTrue(result)

        # Verify data in primary SQL
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 1)

        # Verify data also in parallel FILE
        with open(self.filename1) as f:
            line = f.readline().strip()
            parsed = json.loads(line)
            self.assertIn(topic, parsed)

    def test_multiple_parallels(self):
        """Test that data is sent to multiple parallel outputs."""
        topic = "multi_parallel"
        data = {"msg": "broadcast"}

        primary = FILE(filename=self.filename1)
        parallel1 = FILE(filename=self.filename2)
        parallel2 = SQL(filename=self.database)

        primary.add_parallel(parallel1)
        primary.add_parallel(parallel2)

        result = primary.transmit(topic, data)

        self.assertTrue(result)

        # Verify data in primary FILE
        with open(self.filename1) as f:
            line = f.readline().strip()
            parsed = json.loads(line)
            self.assertEqual(parsed, {topic: [data]})

        # Verify data in first parallel FILE
        with open(self.filename2) as f:
            line = f.readline().strip()
            parsed = json.loads(line)
            self.assertEqual(parsed, {topic: [data]})

        # Verify data in second parallel SQL
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE topic = ?", (topic,))
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 1)

    def test_parallel_does_not_affect_primary_return(self):
        """Test that primary returns True even if parallel would fail."""
        topic = "test"
        data = {"key": "value"}

        primary = FILE(filename=self.filename1)
        # A regular file as parent directory fails even as root, unlike /nonexistent;
        # set after construction, which would otherwise try to create that directory
        parallel = FILE(filename=self.filename2)
        parallel.filename = os.path.join(self.filename2, "file.json")

        primary.add_parallel(parallel)

        # Primary should still succeed
        result = primary.transmit(topic, data)

        self.assertTrue(result)

        # Verify data in primary
        with open(self.filename1) as f:
            line = f.readline().strip()
            parsed = json.loads(line)
            self.assertEqual(parsed, {topic: [data]})

    def test_multiple_transmits_to_parallels(self):
        """Test that multiple transmits all go to parallels."""
        primary = FILE(filename=self.filename1)
        parallel = SQL(filename=self.database)

        primary.add_parallel(parallel)

        # Transmit multiple messages
        for i in range(5):
            primary.transmit(f"topic_{i}", {"count": i})

        # Verify all 5 in primary FILE
        with open(self.filename1) as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 5)

        # Verify all 5 in parallel SQL
        conn = sqlite3.connect(self.database)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 5)

    def test_parallel_with_none_data(self):
        """Test that None data doesn't cause issues with parallels."""
        primary = FILE(filename=self.filename1)
        parallel = SQL(filename=self.database)

        primary.add_parallel(parallel)

        result = primary.transmit("topic", None)

        self.assertTrue(result)

        # Both should be empty since None data is skipped
        if os.path.exists(self.filename1):
            with open(self.filename1) as f:
                content = f.read().strip()
                self.assertEqual(content, "")

    def test_add_parallel_validates_type(self):
        """Test that add_parallel raises error for non-OutputModule."""
        primary = FILE(filename=self.filename1)

        with self.assertRaises(Exception):
            primary.add_parallel("not an output module")

    def test_parallels_list_is_independent(self):
        """Test that each module has its own parallels list."""
        module1 = FILE(filename=self.filename1)
        module2 = FILE(filename=self.filename2)
        parallel = SQL(filename=self.database)

        module1.add_parallel(parallel)

        # module2 should not have any parallels
        self.assertEqual(len(module1._parallels), 1)
        self.assertEqual(len(module2._parallels), 0)


if __name__ == "__main__":
    unittest.main()
