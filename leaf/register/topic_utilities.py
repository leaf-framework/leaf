import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml  # type: ignore

CURR_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_EQUIPMENT_ACTIONS_YAML = os.path.join(CURR_DIR, "equipment_actions.yaml")
DEFAULT_REQUIRED_FIELDS_YAML = os.path.join(CURR_DIR, "equipment_data.yaml")


@dataclass
class Topic:
    parts: dict[str, str] = field(default_factory=dict)
    action: str | None = None

    def __getitem__(self, key: str) -> str | None:
        return self.parts.get(key)

    def __setitem__(self, key: str, value: str):
        self.parts[key] = value

    def __getattr__(self, name: str) -> str | None:
        if name in self.parts:
            return self.parts[name]
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value):
        if name in self.__dataclass_fields__:
            super().__setattr__(name, value)
        else:
            self.parts[name] = value

    def __delattr__(self, name: str):
        if name in self.parts:
            del self.parts[name]
        else:
            super().__delattr__(name)

    def to_dict(self):
        d = self.parts.copy()
        d["action"] = self.action
        return d


class TopicUtility:
    def __init__(self, yaml_path: str | None = None, required_fields_path: str | None = None):
        """
        Initialize TopicUtility by loading:
        - A YAML file with topic templates.
        - A separate YAML file with required field definitions.
        """
        if not yaml_path:
            yaml_path = DEFAULT_EQUIPMENT_ACTIONS_YAML
        if not required_fields_path:
            required_fields_path = DEFAULT_REQUIRED_FIELDS_YAML

        # Load the topic templates from YAML
        with open(yaml_path, encoding="utf-8") as f:
            self._raw_dict = yaml.safe_load(f)

        # Load required fields from the separate YAML file
        with open(required_fields_path, encoding="utf-8") as f:
            self._required_fields = yaml.safe_load(f)  # Expecting a dictionary from YAML

        self._templates: dict[str, str] = {}
        self._collect_templates(self._raw_dict)
        self.root = _TemplateGroup(self._raw_dict, self)

    def __getattr__(self, name: str) -> Any:
        """
        Handle dynamic attribute access:
        - If it's a required field from the YAML, return its name.
        - Otherwise, delegate to the root template group.
        """
        if name in self._required_fields:
            return name  # Return the key name itself (e.g., "adapter_id" when accessing topic_utilities.adapter_id)

        try:
            return getattr(self.root, name)
        except AttributeError:
            raise AttributeError(f"No attribute '{name}' found in TopicUtility or root group.")

    def _collect_templates(self, node: dict | str, prefix: str = ""):
        if isinstance(node, dict):
            for key, value in node.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                self._collect_templates(value, new_prefix)
        else:
            self._templates[prefix] = node

    def render_template(self, template_str: str, placeholders: dict[str, str]) -> str:
        # Strip optional <root>/ prefix from template when root is not provided
        if not placeholders.get("root"):
            template_str = re.sub(r"^<root>/", "", template_str)

        def _replace(m):
            ph_name = m.group(1)
            return placeholders.get(ph_name, "+")

        return re.sub(r"<([^>]+)>", _replace, template_str)

    def parse_topic(self, topic_str: str) -> Topic:
        for _, template_str in self._templates.items():
            try:
                return self._attempt_match(template_str, topic_str)
            except ValueError:
                pass
            # Also try matching without the optional <root>/ prefix
            template_no_root = re.sub(r"^<root>/", "", template_str)
            if template_no_root != template_str:
                try:
                    return self._attempt_match(template_no_root, topic_str)
                except ValueError:
                    pass
        raise ValueError(f"No template matched the topic '{topic_str}'.")

    def is_complete_topic(self, topic_str: str) -> bool:
        return ("+" not in topic_str) and ("#" not in topic_str)

    def is_instance(self, topic: str, template: str) -> bool:
        t_parts = template.split("/")
        top_parts = topic.split("/")

        i = 0
        while i < len(t_parts):
            if t_parts[i] == "#":
                return True
            if i >= len(top_parts):
                return False
            if t_parts[i] != "+" and t_parts[i] != top_parts[i]:
                return False
            i += 1
        return i == len(top_parts)

    def _attempt_match(self, template_str: str, topic_str: str) -> Topic:
        template_parts = template_str.split("/")
        topic_parts = topic_str.split("/")

        if len(template_parts) != len(topic_parts):
            raise ValueError("Segment count mismatch.")

        matched_topic = Topic()
        for t_part, top_part in zip(template_parts, topic_parts):
            if t_part.startswith("<") and t_part.endswith(">"):
                placeholder_name = t_part[1:-1]
                matched_topic[placeholder_name] = top_part
            else:
                if t_part != top_part:
                    raise ValueError(f"Mismatch: '{t_part}' vs '{top_part}'.")

        for t_part, top_part in zip(reversed(template_parts), reversed(topic_parts)):
            if not (t_part.startswith("<") and t_part.endswith(">")):
                matched_topic.action = top_part
                break

        return matched_topic


class _TemplateGroup:
    def __init__(self, data: dict | str, parent_util: TopicUtility):
        self._data = data
        self._util = parent_util

    def __getattr__(self, item: str) -> Any:
        """Access subgroups or final templates by dot notation."""
        if not isinstance(self._data, dict):
            raise AttributeError(f"Cannot get '{item}' from a final template node.")
        try:
            child = self._data[item]
        except KeyError:
            raise AttributeError(f"No attribute '{item}' in this template group.")
        if isinstance(child, dict):
            return _TemplateGroup(child, self._util)
        if isinstance(child, str):

            def _render(**kwargs) -> str:
                return self._util.render_template(child, kwargs)

            return _render
        raise AttributeError(f"Unexpected type {type(child)} for '{item}'")


topic_utilities = TopicUtility()
