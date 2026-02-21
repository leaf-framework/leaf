import os
import sys
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.simple_watcher import SimpleWatcher
from leaf.register.metadata import MetadataManager


class TestSimpleWatcher(unittest.TestCase):
    def setUp(self):
        self.metadata_manager = MetadataManager()

    def test_returns_measurement_trigger(self):
        """Test SimpleWatcher returns measurement trigger on each poll"""
        watcher = SimpleWatcher(metadata_manager=self.metadata_manager, interval=1)

        # Poll multiple times - should always return measurement trigger
        for _ in range(5):
            result = watcher._fetch_data()
            self.assertIsNotNone(result["measurement"])
            self.assertIsInstance(result["measurement"], dict)
            # Content doesn't matter - interpreter ignores it and fetches real data

    def test_includes_start_stop_keys(self):
        """Test SimpleWatcher returns all required keys"""
        watcher = SimpleWatcher(metadata_manager=self.metadata_manager, interval=1)

        result = watcher._fetch_data()

        # Must have all three keys for PollingWatcher compatibility
        self.assertIn("measurement", result)
        self.assertIn("start", result)
        self.assertIn("stop", result)

        # Start and stop should always be None
        self.assertIsNone(result["start"])
        self.assertIsNone(result["stop"])

    def test_initial_state(self):
        """Test SimpleWatcher initializes with correct interval"""
        watcher = SimpleWatcher(metadata_manager=self.metadata_manager, interval=5)

        self.assertEqual(watcher._interval, 5)
        self.assertIsNotNone(watcher._metadata_manager)


if __name__ == "__main__":
    unittest.main()
