import json
import os
from typing import Any, cast

import yaml  # type: ignore

curr_dir = os.path.dirname(os.path.realpath(__file__))
equipment_data_fn = os.path.join(curr_dir, "equipment_data.yaml")

equipment_key = "equipment"
instance_key = "instance"
from leaf.register.topic_utilities import _TemplateGroup, topic_utilities


class MetadataManager:
    """
    Manages your equipment metadata (e.g., organisation, equipment_id, instance_id)
    and delegates template generation to a TopicUtility instance.
    """

    def __init__(self) -> None:
        """Initialize with optional TopicUtility (or create one)."""
        self._instance_data: dict = {}
        self._equipment_data: dict = {}
        self._required_keys: set[str] = set()
        self._load_required_keys()

    def _load_required_keys(self):
        """Load required keys from equipment_data.yaml, if used."""
        with open(equipment_data_fn) as file:
            yaml_content = yaml.safe_load(file)
            self._required_keys = set(yaml_content.keys())

    def get_data(self) -> dict:
        """Returns both the equipment and instance data in one dictionary"""
        data = {equipment_key: self._equipment_data.copy(), instance_key: self._instance_data}
        return data

    def add_data(self, data):
        self._instance_data.update(data[instance_key])
        self._equipment_data.update(data[equipment_key])

    # --- Instance Data ---
    def add_instance_value(self, key: str, value: Any) -> None:
        """Set a single piece of metadata."""
        self._instance_data[key] = value

    def add_instance_data(self, data_or_path: dict | str) -> None:
        """Load instance data from a dict or JSON file."""
        if isinstance(data_or_path, dict):
            self._instance_data.update(data_or_path)
        else:
            with open(data_or_path) as file:
                data = yaml.safe_load(file)
            self._instance_data.update(data)

    def get_instance_data(self, key: str | None = None) -> Any:
        """Retrieve top-level metadata by key."""
        if key is None:
            return self._instance_data
        return self._instance_data.get(key)

    def instance_tags(self) -> dict[str, str]:
        """The organisation and department tags every point of this instance carries."""
        tags: dict[str, str] = {}
        for key in ("organisation", "department"):
            value = cast(object, self._instance_data.get(key))  # pyright: ignore[reportUnknownMemberType]
            if value:
                tags[key] = str(value)
        return tags

    def get_instance_id(self) -> str:
        """Convenience accessor for 'instance_id' in equipment."""
        return self._instance_data.get("instance_id", "")

    # -- Equipment Data ---
    def add_equipment_value(self, key: str, value: Any) -> None:
        """Set a single piece of metadata."""
        self._equipment_data[key] = value

    def add_equipment_data(self, data_or_path: dict | str) -> None:
        """Load instance data from a dict or JSON file."""
        if isinstance(data_or_path, dict):
            data = data_or_path
        else:
            with open(data_or_path) as file:
                if data_or_path.endswith(".json"):
                    data = json.load(file)
                else:
                    data = yaml.safe_load(file)

        if "adapter_id" in data:
            self._equipment_data["adapter_id"] = data["adapter_id"]
        if "equipment_data" in data:
            data = data["equipment_data"]
        else:
            data = data
        self._equipment_data.update(data)

    def get_equipment_data(self, key: str | None = None) -> Any:
        """Retrieve top-level metadata by key."""
        if key is None:
            return self._equipment_data
        return self._equipment_data.get(key)

    def is_valid(self) -> bool:
        """Check if all required keys are present in the equipment sub-dict."""
        eq_data = self._instance_data.copy()
        eq_data.update(self._equipment_data)
        missing = [k for k in self._required_keys if k not in eq_data]
        return not missing

    def get_missing_metadata(self):
        eq_data = self._instance_data.copy()
        eq_data.update(self._equipment_data)
        return [k for k in self._required_keys if k not in eq_data]

    def __getattr__(self, name: str) -> Any:
        """
        If the user does 'metadata_manager.start()', we look up
        'start' in the TopicUtility's root group, and wrap it to
        auto-fill placeholders with equipment metadata.
        """
        try:
            sub = getattr(topic_utilities.root, name)
        except AttributeError:
            raise AttributeError(f"No attribute '{name}' in MetadataManager or templates.")

        if callable(sub):

            def _wrapper(**overrides) -> str:
                return cast(str, sub(**self._placeholders(overrides)))

            return _wrapper
        if isinstance(sub, _TemplateGroup):
            return _ManagerGroup(sub, self)

        return sub

    def _placeholders(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Template placeholders from the equipment and instance data, then the caller's overrides."""
        data = self.get_equipment_data().copy()
        data.update(self.get_instance_data())
        # A point that names no entity is about the instance itself
        if data.get("instance_id"):
            data.setdefault("entity", data["instance_id"])
        return {**data, **overrides}


class _ManagerGroup:
    """
    Proxy class that wraps a _TemplateGroup so deeper calls also fill
    placeholders from the MetadataManager's equipment data.
    """

    def __init__(self, group: _TemplateGroup, manager: MetadataManager):
        self._group = group
        self._manager = manager

    def __getattr__(self, item: str) -> Any:
        sub = getattr(self._group, item)
        if callable(sub):

            def _wrapper(**overrides) -> str:
                return cast(str, sub(**self._manager._placeholders(overrides)))  # pyright: ignore[reportPrivateUsage]

            return _wrapper
        if isinstance(sub, _TemplateGroup):
            return _ManagerGroup(sub, self._manager)
        return sub
