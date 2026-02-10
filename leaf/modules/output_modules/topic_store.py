from typing import Any


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

    def set(self, topic: str, message: Any) -> None:
        """Split topic by '/' and store message at the deepest level."""
        parts = [p for p in topic.split("/") if p]
        node = self._store
        for part in parts:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node["_value"] = message

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
