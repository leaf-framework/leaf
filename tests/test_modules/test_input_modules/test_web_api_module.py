import os
import sys

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

import unittest
from unittest.mock import MagicMock, patch

from requests.models import Response

from leaf.modules.input_modules.http_watcher import HTTPWatcher, URLState
from leaf.register.metadata import MetadataManager


class TestURLState(unittest.TestCase):
    def setUp(self):
        self.url_state = URLState("measurement")

    def mock_response(self, etag=None, last_modified=None, json_data=None) -> Response:
        response = MagicMock(spec=Response)
        response.headers = {}
        if etag:
            response.headers["ETag"] = etag
        if last_modified:
            response.headers["Last-Modified"] = last_modified
        response.json = MagicMock(return_value=json_data or {})
        return response

    def test_update_with_new_data(self):
        response = self.mock_response(
            json_data={"key": "new_data"},
            etag="12345",
            last_modified="Mon, 26 Jul 2021 05:00:00 GMT",
        )
        new_data = self.url_state.update_from_response(response)
        self.assertEqual(new_data, {"key": "new_data"})
        self.assertEqual(self.url_state.previous_data, {"key": "new_data"})

    def test_no_update_when_etag_matches(self):
        response = self.mock_response(etag="12345", json_data={"key": "data"})
        self.url_state.etag = "12345"
        new_data = self.url_state.update_from_response(response)
        self.assertIsNone(new_data)

    def test_update_on_different_last_modified(self):
        response = self.mock_response(
            last_modified="Mon, 26 Jul 2021 05:00:00 GMT", json_data={"key": "updated_data"}, etag="12345"
        )
        self.url_state.last_modified = "Mon, 26 Jul 2021 04:00:00 GMT"
        new_data = self.url_state.update_from_response(response)
        self.assertEqual(new_data, {"key": "updated_data"})


class TestAPIWatcher(unittest.TestCase):
    def setUp(self):
        metadata_manager = MetadataManager()

        self.mock_measurement_callback = MagicMock()
        self.mock_start_callback = MagicMock()
        self.mock_stop_callback = MagicMock()
        self.api_watcher = HTTPWatcher(
            metadata_manager=metadata_manager,
            measurement_url="http://example.com/measurement",
            start_url="http://example.com/start",
            stop_url="http://example.com/stop",
            interval=60,
            headers={"Authorisation": "Bearer test-token"},
        )

    def mock_response(self, status_code=200, etag=None, last_modified=None, json_data=None):
        response = MagicMock(spec=Response)
        response.status_code = status_code
        response.headers = {}
        if etag:
            response.headers["ETag"] = etag
        if last_modified:
            response.headers["Last-Modified"] = last_modified
        response.json = MagicMock(return_value=json_data or {})
        return response

    @patch("requests.get")
    def test_initialisation(self, mock_get):
        self.assertIn("measurement", self.api_watcher._url_states)
        self.assertIn("start", self.api_watcher._url_states)
        self.assertIn("stop", self.api_watcher._url_states)
        self.assertEqual(self.api_watcher._interval, 60)
        self.assertEqual(self.api_watcher._headers, {"Authorisation": "Bearer test-token"})

    @patch("requests.get")
    def test_fetch_data_no_change(self, mock_get):
        initial_response = self.mock_response(etag="12345", json_data={"initial": "data"})
        mock_get.return_value = initial_response
        self.api_watcher._fetch_data()

        mock_get.side_effect = [
            self.mock_response(status_code=304),
            self.mock_response(status_code=304),
            self.mock_response(status_code=304),
        ]
        fetched_data = self.api_watcher._fetch_data()
        self.assertIsNone(fetched_data["measurement"])
        self.assertIsNone(fetched_data["start"])
        self.assertIsNone(fetched_data["stop"])


if __name__ == "__main__":
    unittest.main()


def test_url_state_without_headers_only_changed_content_counts() -> None:
    # Servers like the IndPenSim reactor API send neither ETag nor Last-Modified
    state = URLState("measurement")
    results: list[object] = []
    for data in ({"k": 1}, {"k": 1}, {"k": 2}):
        response = MagicMock(spec=Response)
        response.configure_mock(headers={}, **{"json.return_value": data})
        # update_from_response() returns an unparametrised dict
        results.append(state.update_from_response(response))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    assert results == [{"k": 1}, None, {"k": 2}]
