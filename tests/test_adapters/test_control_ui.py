import json
import logging
from pathlib import Path
from typing import cast, override
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


class Refuser(AbstractController):
    @override
    def control(self, topic: str, data: str) -> None:
        raise RuntimeError("409 Conflict")


def test_send_control_failure_is_reported_and_raised() -> None:
    reported: list[Exception] = []
    adapter = mock.MagicMock(
        _controller=Refuser(),
        _controls=[],
        _metadata_manager=_metadata(),
        _logger=logging.getLogger(),
        _handle_exception=reported.append,
    )
    with pytest.raises(RuntimeError):
        EquipmentAdapter.send_control(adapter, '{"fields": {}}')
    # The UI shows the exception; the error holder puts it on the error topic
    [error] = reported
    assert isinstance(error, AdapterLogicError)
    assert "409 Conflict" in str(error)


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


class ErrorRecorder:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def transmit_error(self, error: dict[str, str]) -> None:
        self.sent.append(error)


def test_errors_are_published_once_not_once_per_process() -> None:
    first, second = ErrorRecorder(), ErrorRecorder()
    adapter = mock.MagicMock(_processes=[first, second])
    EquipmentAdapter.transmit_errors(adapter, [(AdapterLogicError("boom"), "now")])
    assert len(first.sent) == 1
    assert second.sent == []


def test_result_record_puts_source_and_status_in_the_tags() -> None:
    from leaf.adapters.control_spec import result_record

    sent = '{"measurement": "leaf_test", "tags": {"metric": "T_sp", "entity": "r1"}, "fields": {"value": 303.0}}'
    record = result_record(sent, "ui")
    assert record["measurement"] == "leaf_test"
    assert record["tags"] == {"metric": "T_sp", "entity": "r1", "source": "ui", "status": "applied"}
    assert record["fields"] == {"value": 303.0}
    assert isinstance(record["timestamp"], float)

    rejected = result_record(sent, "mqtt", ValueError("T_sp = 2000.0 is above its maximum 373.15"))
    assert rejected["tags"] == {
        "metric": "T_sp",
        "entity": "r1",
        "source": "mqtt",
        "status": "rejected",
        "error": "T_sp = 2000.0 is above its maximum 373.15",
    }
    assert rejected["fields"] == {"value": 303.0}

    unreadable = result_record("not json", "mqtt", ValueError("bad"), {"entity": "r1"})
    assert unreadable["tags"] == {"entity": "r1", "source": "mqtt", "status": "rejected", "error": "bad"}
    assert unreadable["fields"] == {"message": "not json"}


class OutputRecorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def transmit(self, topic: str, data: object) -> bool:
        self.sent.append((topic, data))
        return True


def _adapter_with(controller: AbstractController, output: OutputRecorder) -> mock.MagicMock:
    """A stand-in adapter whose _report_control is the real one, publishing to output."""
    adapter = mock.MagicMock(
        _controller=controller, _controls=[], _metadata_manager=_metadata(), _logger=logging.getLogger(), _output=output
    )

    def report(topic: str, data: str, source: str, error: Exception | None = None) -> None:
        EquipmentAdapter._report_control(adapter, topic, data, source, error)  # pyright: ignore[reportPrivateUsage]

    adapter.configure_mock(_report_control=report)
    return adapter


def test_ui_and_mqtt_commands_are_published_on_control_result() -> None:
    output = OutputRecorder()
    adapter = _adapter_with(Recorder(), output)
    message = '{"tags": {"metric": "step"}, "fields": {"value": "next"}}'
    EquipmentAdapter.send_control(adapter, message)
    EquipmentAdapter._on_control(adapter, "leaf/wur/ssb/leaf_test/r1/control", message)  # pyright: ignore[reportPrivateUsage]
    topics = [topic for topic, _ in output.sent]
    assert all(topic.endswith("/r1/control/result") for topic in topics)
    sources = [cast(dict[str, dict[str, str]], record)["tags"]["source"] for _, record in output.sent]
    assert sources == ["ui", "mqtt"]


def test_control_results_carry_the_instance_tags() -> None:
    output = OutputRecorder()
    adapter = _adapter_with(Recorder(), output)
    EquipmentAdapter.send_control(adapter, '{"tags": {"metric": "step"}, "fields": {"value": "next"}}')
    [(_, record)] = output.sent
    tags = cast(dict[str, dict[str, str]], record)["tags"]
    assert (tags["organisation"], tags["department"]) == ("wur", "ssb")
    # leafobject requires an entity; a control acts on the instance itself
    assert tags["entity"] == "r1"


def test_rejected_commands_are_published_too() -> None:
    output = OutputRecorder()
    adapter = _adapter_with(Refuser(), output)
    with pytest.raises(RuntimeError):
        EquipmentAdapter.send_control(adapter, '{"tags": {"metric": "step"}, "fields": {"value": "next"}}')
    [(_, record)] = output.sent
    assert cast(dict[str, dict[str, str]], record)["tags"]["status"] == "rejected"


def test_result_record_is_a_valid_leafpoint() -> None:
    from leaf.adapters.control_spec import result_record

    # Messages LEAF rejects still become a LeafPoint: tags as text, at least one field
    record = result_record(
        '{"tags": {"metric": "T_sp", "reactor": 1}}', "mqtt", ValueError("needs fields"), {"entity": "r1"}
    )
    assert record["tags"] == {
        "metric": "T_sp",
        "reactor": "1",
        "entity": "r1",
        "source": "mqtt",
        "status": "rejected",
        "error": "needs fields",
    }
    assert record["fields"] == {"message": '{"tags": {"metric": "T_sp", "reactor": 1}}'}

    nested = result_record('{"tags": {"metric": "x"}, "fields": {"value": {"a": 1}}}', "ui", None, {"entity": "r1"})
    assert nested["fields"] == {"value": '{"a": 1}'}


def test_control_result_topic_is_the_one_published_on() -> None:
    # The registered topic must match <control topic>/result, which _report_control builds
    manager = MetadataManager()
    manager.add_equipment_value("adapter_id", "leaf_test")
    manager.add_instance_value("organisation", "wur")
    manager.add_instance_value("department", "ssb")
    manager.add_instance_value("instance_id", "r1")
    # Topic builders are generated at runtime, so the checker sees them as Any
    assert manager.control_result() == f"{manager.control()}/result"  # pyright: ignore[reportAny]
