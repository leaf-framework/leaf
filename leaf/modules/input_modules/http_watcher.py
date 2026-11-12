from collections.abc import Callable
from typing import Any

import requests
from requests import RequestException, Response

from leaf.error_handler.error_holder import ErrorHolder
from leaf.modules.input_modules.polling_watcher import PollingWatcher
from leaf.register.metadata import MetadataManager
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.security import http_warnings

logger = get_logger(__name__, log_file="input_module.log")

# Without a timeout a server that never answers blocks polling forever.
DEFAULT_TIMEOUT = 30.0


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
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        # Only a header the server sent can say "unchanged"; two missing ones are not a match
        if etag is not None and etag == self.etag:
            return None
        if last_modified is not None and last_modified == self.last_modified:
            return None

        current_data = response.json()

        if etag is None and last_modified is None:
            if current_data == self.previous_data:
                return None

        self.etag = etag
        self.last_modified = last_modified
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
        timeout: float = DEFAULT_TIMEOUT,
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
            timeout (float): Seconds to wait for a response before the request counts as failed.
            callbacks (Optional[List[Callable]]): Callback functions to execute on data updates.
            error_holder (Optional[ErrorHolder]): Optional error management object.
        """
        super().__init__(
            interval=interval, metadata_manager=metadata_manager, callbacks=callbacks, error_holder=error_holder
        )

        self._headers: dict[str, str] = headers or {}
        self._timeout: float = timeout

        self._urls: dict[str, str] = {"measurement": measurement_url}
        # URLs whose last request failed (bad host, 404, ...), so the UI can show the input as down.
        self._failing_urls: set[str] = set()
        self._url_states: dict[str, URLState] = {"measurement": URLState("measurement")}

        if start_url:
            self._urls["start"] = start_url
            self._url_states["start"] = URLState("start")

        if stop_url:
            self._urls["stop"] = stop_url
            self._url_states["stop"] = URLState("stop")

    def is_connected(self) -> bool:
        if not self.is_running():
            return False
        if self._failing_urls:
            return False
        return True

    def security_warnings(self) -> list[str]:
        issues: list[str] = []
        for url in self._urls.values():
            issues += http_warnings("HTTP input", url)
        return issues

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
                response = requests.get(url, headers=headers, timeout=self._timeout)
                response.raise_for_status()
            except RequestException as e:
                self._failing_urls.add(url)
                logger.error(f"[HTTPWatcher] Failed to fetch {key} from {url}: {e}", exc_info=True)
                continue
            self._failing_urls.discard(url)

            if response.status_code == 200:
                new_data = state.update_from_response(response)
                if new_data:
                    result[key] = new_data

        return result
