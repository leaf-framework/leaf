import json
import logging
from pathlib import Path
from typing import override
from unittest import mock

import pytest

from leaf.adapters.control_spec import read_controls
from leaf.adapters.equipment_adapter import AbstractController, EquipmentAdapter
from leaf.error_handler.exceptions import AdapterLogicError
from leaf.register.metadata import MetadataManager
from leaf.ui.tabs.control import control_point, parse_fields, parse_value


def _metadata() -> MetadataManager:
    mm = MetadataManager()
    mm.add_equipment_value("adapter_id", "leaf_test")
    for key, value in {"instance_id": "r1", "organisation": "wur", "department": "ssb"}.items():
        mm.add_instance_value(key, value)
    return mm


class Recorder(AbstractController):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[tuple[str, str]] = []

    @override
    def control(self, topic: str, data: str) -> None:
        self.received.append((topic, data))


def test_send_control_hands_message_to_controller() -> None:
    recorder = Recorder()
    adapter = mock.MagicMock(
        _controller=recorder, _controls=[], _metadata_manager=_metadata(), _logger=logging.getLogger()
    )
    EquipmentAdapter.send_control(adapter, '{"fields": {}}')
    [(topic, data)] = recorder.received
    assert topic.endswith("/r1/control")
    assert data == '{"fields": {}}'


def test_send_control_without_controller_raises() -> None:
    adapter = mock.MagicMock(_controller=None)
    with pytest.raises(AdapterLogicError):
        EquipmentAdapter.send_control(adapter, "{}")


def test_read_controls_from_json_and_yaml(tmp_path: Path) -> None:
    assert read_controls(str(tmp_path)) == []
    _ = (tmp_path / "device.yaml").write_text("controls:\n  - metric: step\n    type: choice\n")
    assert read_controls(str(tmp_path)) == [{"metric": "step", "type": "choice"}]
    _ = (tmp_path / "device.json").write_text(json.dumps({"controls": [{"metric": "T_sp"}, "junk"]}))
    assert read_controls(str(tmp_path)) == [{"metric": "T_sp"}]


@pytest.mark.parametrize(
    "kind, raw, expected",
    [("number", 305, 305.0), ("choice", "paused", "paused"), ("text", "because", "because")],
)
def test_parse_value(kind: str, raw: object, expected: object) -> None:
    assert parse_value(kind, raw, ["paused", "running"]) == expected


@pytest.mark.parametrize(
    "kind, raw",
    [("number", None), ("number", True), ("number", "hot"), ("choice", "exploded"), ("text", ""), ("colour", "red")],
)
def test_parse_value_rejects(kind: str, raw: object) -> None:
    with pytest.raises(ValueError):
        _ = parse_value(kind, raw, ["paused", "running"])


def test_parse_fields_skips_empty_optional_and_requires_the_rest() -> None:
    fields: list[dict[str, object]] = [
        {"name": "reason", "type": "text", "required": False},
        {"name": "rate", "type": "number"},
    ]
    assert parse_fields(fields, {"reason": "", "rate": 2}) == {"rate": 2.0}
    with pytest.raises(ValueError):
        _ = parse_fields(fields, {"reason": "x"})


def test_control_point_is_a_leafpoint_setting_metric_to_value() -> None:
    point = control_point(_metadata(), "T_sp", 305.0, {"reason": "test"})
    assert point["measurement"] == "leaf_test"
    assert point["tags"] == {"instance_id": "r1", "organisation": "wur", "department": "ssb", "metric": "T_sp"}
    assert point["fields"] == {"value": 305.0, "reason": "test"}
    assert isinstance(point["timestamp"], float)


def test_discovered_mqtt_output_is_the_mqtt_class() -> None:
    """Loading mqtt.py from its path made a second MQTT class, so control: true always failed."""
    from leaf.modules.output_modules.mqtt import MQTT
    from leaf.registry.discovery import discover_output_modules

    [(name, cls)] = discover_output_modules({"mqtt"})
    assert name == "mqtt"
    assert cls is MQTT


def test_controllable_instances_only_lists_adapters_with_a_controller() -> None:
    from leaf.ui.tabs.control import controllable_instances
    from leaf.utility.running_adapters import adapters

    with_controller = mock.MagicMock(spec=EquipmentAdapter)
    with_controller.configure_mock(**{"has_controller.return_value": True})
    without = mock.MagicMock(spec=EquipmentAdapter)
    without.configure_mock(**{"has_controller.return_value": False})
    adapters.extend([with_controller, without])
    try:
        assert controllable_instances() == [with_controller]
    finally:
        adapters.clear()
