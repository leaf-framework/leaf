import threading
import time
from collections import deque
from typing import Any, cast

# Points kept per topic (one metric each) for the Monitoring plot; in memory, so it starts empty after a restart
HISTORY_LENGTH = 1000


class TopicStore:
    """
    A lightweight nested-dict wrapper that stores the latest message
    per hierarchical topic. Topics are split on '/' and stored at
    the leaf node using a '_value' sentinel key.

    Example:
        store.set("unlock/proj1/dev1/temp", {"value": 23.5})
        # Internal: {"unlock": {"proj1": {"dev1": {"temp": {"_value": {"value": 23.5}}}}}}
    """

    def __init__(self) -> None:
        self._store: dict = {}
        self._history: dict[str, deque[tuple[float, float]]] = {}
        # Adapters write from their own threads while the UI reads
        self._history_lock: threading.Lock = threading.Lock()

    def set(self, topic: str, message: Any) -> None:
        """Split topic by '/' and store message at the deepest level."""
        parts = [p for p in topic.split("/") if p]
        node = self._store
        for part in parts:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node["_value"] = message
        payload = cast(object, message)
        self._record_history(topic, payload)

    def _record_history(self, topic: str, message: object) -> None:
        """Keep the numeric "value" field of point messages (a point dict or a list of them)."""
        if isinstance(message, list):
            points = cast(list[object], message)
        else:
            points = [message]
        for point in points:
            sample = _point_sample(point)
            if sample is None:
                continue
            key = history_key(topic, point)
            with self._history_lock:
                history = self._history.setdefault(key, deque(maxlen=HISTORY_LENGTH))
                history.append(sample)

    def get_history(self) -> dict[str, list[tuple[float, float]]]:
        """(timestamp, value) pairs per history key (see history_key), oldest first."""
        with self._history_lock:
            return {topic: list(points) for topic, points in self._history.items()}

    def get(self, topic: str) -> Any:
        """Retrieve the latest message for a topic, or None."""
        parts = [p for p in topic.split("/") if p]
        node = self._store
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        if isinstance(node, dict):
            return node.get("_value")
        return None

    def get_subtree(self, topic: str) -> dict | None:
        """Get the full nested dict under a topic prefix."""
        parts = [p for p in topic.split("/") if p]
        node = self._store
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node if isinstance(node, dict) else None

    def get_all(self) -> dict:
        """Return the full nested store."""
        return self._store


# Separates the topic from the point's entity tag in a history key
ENTITY_SEPARATOR = "#"


def history_key(topic: str, point: object) -> str:
    """Topic plus the point's "entity" tag, since one topic can carry several entities (e.g. the wells of a plate)."""
    tags = cast(dict[str, object], point).get("tags")
    if isinstance(tags, dict):
        entity = cast(dict[str, object], tags).get("entity")
        if isinstance(entity, str) and entity:
            return f"{topic}{ENTITY_SEPARATOR}{entity}"
    return topic


def _point_sample(point: object) -> tuple[float, float] | None:
    """(timestamp, value) of a LeafPoint JSON dict with a numeric fields.value, or None."""
    if not isinstance(point, dict):
        return None
    point_dict = cast(dict[str, object], point)
    fields = point_dict.get("fields")
    if not isinstance(fields, dict):
        return None
    value = cast(dict[str, object], fields).get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    timestamp = point_dict.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        timestamp = time.time()
    return (float(timestamp), float(value))
