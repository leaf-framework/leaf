import json
import logging
from typing import override
from unittest import mock

import pytest

from leaf.adapters.control_spec import Control, apply_limits, check_control
from leaf.adapters.equipment_adapter import AbstractController, EquipmentAdapter
from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterBuildError, LEAFError
from leaf.ui.tabs.control import range_hint
from leaf.utility.running_utilities import _attach_controller  # pyright: ignore[reportPrivateUsage]

CONTROLS: list[Control] = [
    {"metric": "T_sp", "type": "number", "min": 290, "max": 310, "reset": "recipe"},
    {"metric": "Fs", "type": "number"},
    {"metric": "batch", "type": "choice", "options": ["paused", "running"]},
    {"metric": "note", "type": "text"},
]


def _point(metric: str, value: object) -> str:
    return json.dumps({"measurement": "m", "tags": {"metric": metric}, "fields": {"value": value}})


def test_limits_narrow_the_adapter_range() -> None:
    [t_sp, fs, *_] = apply_limits(CONTROLS, {"T_sp": {"min": 295, "max": 305}, "Fs": {"max": 80}})
    assert (t_sp["min"], t_sp["max"]) == (295.0, 305.0)
    assert fs["max"] == 80.0
    assert CONTROLS[0]["min"] == 290  # the adapter's own list is not changed


@pytest.mark.parametrize(
    "limits",
    [
        {"T_sp": {"min": 280}},  # wider than the adapter allows
        {"T_sp": {"max": 320}},
        {"pressure": {"max": 2}},  # not a declared control
        {"batch": {"max": 1}},  # not a number control
        {"T_sp": {"step": 1}},  # only min and max
        {"T_sp": {"min": "low"}},
        {"T_sp": 300},
    ],
)
def test_limits_that_do_not_fit_are_rejected(limits: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _ = apply_limits(CONTROLS, limits)


@pytest.mark.parametrize(
    "metric, value",
    [("T_sp", 300), ("T_sp", 290), ("T_sp", "recipe"), ("Fs", 1e6), ("batch", "paused"), ("note", "hi")],
)
def test_allowed_messages_pass(metric: str, value: object) -> None:
    check_control(CONTROLS, _point(metric, value))


@pytest.mark.parametrize(
    "metric, value",
    [
        ("T_sp", 289.9),
        ("T_sp", 311),
        ("T_sp", "hot"),
        ("T_sp", True),
        ("batch", "aborted"),
        ("note", ""),
        ("pressure", 1),
    ],
)
def test_disallowed_messages_are_rejected(metric: str, value: object) -> None:
    with pytest.raises(ValueError):
        check_control(CONTROLS, _point(metric, value))


def test_malformed_messages_are_rejected() -> None:
    for data in ('"text"', '{"tags": {"metric": "T_sp"}}'):
        with pytest.raises(ValueError):
            check_control(CONTROLS, data)


def test_adapters_without_declared_controls_are_not_checked() -> None:
    check_control([], '{"action": "anything"}')


class Recorder(AbstractController):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[str] = []

    @override
    def control(self, topic: str, data: str) -> None:
        self.received.append(data)


def _adapter_with(recorder: Recorder, holder: ErrorHolder) -> mock.MagicMock:
    adapter = mock.MagicMock(_logger=logging.getLogger(), _error_holder=holder)

    def handle(error: LEAFError) -> None:
        EquipmentAdapter._handle_exception(adapter, error)  # pyright: ignore[reportPrivateUsage]

    adapter._handle_exception = handle
    EquipmentAdapter.set_controller(adapter, recorder, apply_limits(CONTROLS, {"T_sp": {"max": 305}}))
    return adapter


def test_mqtt_messages_outside_the_limits_never_reach_the_controller() -> None:
    recorder = Recorder()
    holder = ErrorHolder("r1")
    adapter = _adapter_with(recorder, holder)
    EquipmentAdapter._on_control(adapter, "t", _point("T_sp", 306))  # pyright: ignore[reportPrivateUsage]
    EquipmentAdapter._on_control(adapter, "t", _point("T_sp", 300))  # pyright: ignore[reportPrivateUsage]
    assert recorder.received == [_point("T_sp", 300)]
    assert len(holder.get_unseen_errors()) == 1


def test_ui_messages_outside_the_limits_raise() -> None:
    recorder = Recorder()
    adapter = _adapter_with(recorder, ErrorHolder("r1"))
    with pytest.raises(ValueError):
        EquipmentAdapter.send_control(adapter, _point("T_sp", 306))
    assert recorder.received == []


def test_control_limits_need_control_true() -> None:
    with pytest.raises(AdapterBuildError):
        _attach_controller(mock.MagicMock(), EquipmentAdapter, mock.MagicMock(), False, {"T_sp": {"max": 1}})


def test_range_hint() -> None:
    assert range_hint(295.0, 305.0) == "295 to 305"
    assert range_hint(None, 305.5) == "up to 305.5"
    assert range_hint(295.0, None) == "from 295"
    assert range_hint(None, None) == ""
