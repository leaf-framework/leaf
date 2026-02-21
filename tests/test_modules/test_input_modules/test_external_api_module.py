import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.external_api_watcher import ExternalApiWatcher
from leaf.register.metadata import MetadataManager


class TestExternalApiWatcher(unittest.TestCase):
    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.measurement_fetcher = Mock()
        self.start_fetcher = Mock(return_value=None)
        self.stop_fetcher = Mock(return_value=None)

        self.watcher = ExternalApiWatcher(
            self.metadata_manager,
            measurement_fetcher=self.measurement_fetcher,
            start_fetcher=self.start_fetcher,
            stop_fetcher=self.stop_fetcher,
            interval=60,
        )

    def test_initial_state_tracking(self):
        self.assertIn("measurement", self.watcher._api_states)
        self.assertIn("start", self.watcher._api_states)
        self.assertIn("stop", self.watcher._api_states)

    def test_measurement_fetching(self):
        self.measurement_fetcher.return_value = {"value": 42}
        result = self.watcher._fetch_data()

        self.assertEqual(result["measurement"], {"value": 42})
        self.assertIsNone(result["start"])
        self.assertIsNone(result["stop"])

    def test_start_and_stop_fetching(self):
        self.measurement_fetcher.return_value = None

        self.start_fetcher.return_value = {"status": "started"}
        self.stop_fetcher.return_value = {"status": "stopped"}

        result = self.watcher._fetch_data()

        self.assertEqual(result["start"], {"status": "started"})
        self.assertEqual(result["stop"], {"status": "stopped"})
        self.assertIsNone(result["measurement"])

    def test_no_update_on_same_data(self):
        self.measurement_fetcher.return_value = {"value": 42}
        self.watcher._fetch_data()

        self.measurement_fetcher.return_value = {"value": 42}
        result = self.watcher._fetch_data()

        self.assertIsNone(result["measurement"])

    def test_error_handling_in_fetcher(self):
        self.measurement_fetcher.side_effect = Exception("Fetch error")
        result = self.watcher._fetch_data()

        self.assertIsNone(result["measurement"])


if __name__ == "__main__":
    unittest.main()
