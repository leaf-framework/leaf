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
from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.output_modules.sql import SQL


class TestTopicStoreWithParallelOutputModules(unittest.TestCase):
    def setUp(self):
        # Reset the global topic store between tests
        from leaf.modules.output_modules.topic_store import TopicStore

        OutputModule._global_topic_store = TopicStore()

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

    def test_global_topic_store_aggregates_across_modules(self):
        """Test that the global topic store collects data from all output modules."""
        file_module = FILE(filename=self.filename1)
        sql_module = SQL(filename=self.database)

        file_module.transmit("file/topic", {"source": "file"})
        sql_module.transmit("sql/topic", {"source": "sql"})

        global_store = OutputModule.get_global_topic_store()

        # Both topics should be in the global store, prefixed by module name
        self.assertEqual(global_store.get(f"{file_module.name}/file/topic"), {"source": "file"})
        self.assertEqual(global_store.get(f"{sql_module.name}/sql/topic"), {"source": "sql"})

        # Each instance store should only have its own topic (no prefix)
        self.assertIsNotNone(file_module.get_latest("file/topic"))
        self.assertIsNone(file_module.get_latest("sql/topic"))

        self.assertIsNotNone(sql_module.get_latest("sql/topic"))
        self.assertIsNone(sql_module.get_latest("file/topic"))

    def test_global_topic_store_subtree(self):
        """Test that global store subtree queries work across modules."""
        file_module = FILE(filename=self.filename1)
        sql_module = SQL(filename=self.database)

        file_module.transmit("sensors/temp", {"value": 22.5})
        sql_module.transmit("sensors/humidity", {"value": 60})

        global_store = OutputModule.get_global_topic_store()

        # Subtree by module name shows that module's topics
        file_subtree = global_store.get_subtree(file_module.name)
        self.assertIsNotNone(file_subtree)
        self.assertIn("sensors", file_subtree)

        sql_subtree = global_store.get_subtree(sql_module.name)
        self.assertIsNotNone(sql_subtree)
        self.assertIn("sensors", sql_subtree)

    def test_file_with_sql_parallel(self):
        """Test that transmitting to FILE also sends to SQL parallel."""
        topic = "root/topic/path/to/test_topic"
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

        # Verify global store has the topic prefixed by module name
        global_store = OutputModule.get_global_topic_store()
        self.assertEqual(global_store.get(f"{file_module.name}/{topic}"), data)


if __name__ == "__main__":
    unittest.main()
