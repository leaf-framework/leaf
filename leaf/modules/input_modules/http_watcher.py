from collections.abc import Callable
from typing import Any

import requests
from leaf_register.metadata import MetadataManager
from requests import RequestException, Response

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.polling_watcher import PollingWatcher
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


class URLState:
    """
    Tracks ETag, Last-Modified, and response body
    to detect whether a new API response is worth processing.
    """

    def __init__(self, url_type: str) -> None:
        """
        Initialize URLState.

        Args:
            url_type (str): Identifier for the
            type of URL being tracked.
        """
        self.url_type: str = url_type
        self.etag: str | None = None
        self.last_modified: str | None = None
        self.previous_data: dict | None = None

    def update_from_response(self, response: Response) -> dict | None:
        """
        Update tracking state if the response represents new data.

        Args:
            response (Response): HTTP response to analyze.

        Returns:
            Optional[dict]: Parsed JSON if the response is new; else None.
        """
        if response.headers.get("ETag") == self.etag:
            return None
        if response.headers.get("Last-Modified") == self.last_modified:
            return None

        current_data = response.json()

        if self.etag is None and self.last_modified is None:
            if current_data == self.previous_data:
                return None

        self.etag = response.headers.get("ETag")
        self.last_modified = response.headers.get("Last-Modified")
        self.previous_data = current_data

        return current_data


class HTTPWatcher(PollingWatcher):
    """
    Polls one or more HTTP endpoints periodically using ETag and Last-Modified
    headers to detect meaningful updates. Supports measurement, start, and stop events.
    """

    def __init__(
        self,
        metadata_manager: MetadataManager,
        measurement_url: str,
        start_url: str | None = None,
        stop_url: str | None = None,
        interval: int = 60,
        headers: dict[str, str] | None = None,
        callbacks: list[Callable[[str, Any], None]] | None = None,
        error_holder: ErrorHolder | None = None,
    ) -> None:
        """
        Initialize the HTTPWatcher.

        Args:
            metadata_manager (MetadataManager): Metadata manager instance.
            measurement_url (str): Required URL to poll for measurements.
            start_url (Optional[str]): Optional URL to detect start events.
            stop_url (Optional[str]): Optional URL to detect stop events.
            interval (int): Polling frequency in seconds.
            headers (Optional[Dict[str, str]]): Custom headers to include in all requests.
            callbacks (Optional[List[Callable]]): Callback functions to execute on data updates.
            error_holder (Optional[ErrorHolder]): Optional error management object.
        """
        super().__init__(
            interval=interval, metadata_manager=metadata_manager, callbacks=callbacks, error_holder=error_holder
        )

        self._headers: dict[str, str] = headers or {}

        self._urls: dict[str, str] = {"measurement": measurement_url}
        self._url_states: dict[str, URLState] = {"measurement": URLState("measurement")}

        if start_url:
            self._urls["start"] = start_url
            self._url_states["start"] = URLState("start")

        if stop_url:
            self._urls["stop"] = stop_url
            self._url_states["stop"] = URLState("stop")

    def _fetch_data(self) -> dict[str, dict | None]:
        """
        Fetch data from all configured URLs and detect changes.

        Returns:
            Dict[str, Optional[dict]]: Dictionary with new data for each type.
        """
        result: dict[str, dict | None] = {"measurement": None, "start": None, "stop": None}

        for key, url in self._urls.items():
            state = self._url_states[key]
            headers = self._headers.copy()

            if state.etag:
                headers["If-None-Match"] = state.etag
            if state.last_modified:
                headers["If-Modified-Since"] = state.last_modified

            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
            except RequestException as e:
                logger.error(f"[HTTPWatcher] Failed to fetch {key} from {url}: {e}", exc_info=True)
                continue

            if response.status_code == 200:
                new_data = state.update_from_response(response)
                if new_data:
                    result[key] = new_data

        return result
