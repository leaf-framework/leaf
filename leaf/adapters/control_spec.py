"""
The controls an adapter declares in its device.json, narrowed by an instance's control_limits.

Every control message, from MQTT or the UI, is checked against them before the controller sees it,
so the limits hold however the message arrives. An adapter that declares no controls is not checked.
"""

import json
import os
from typing import cast

import yaml
from leafobject import LeafPoint  # pyright: ignore[reportMissingTypeStubs]

Control = dict[str, object]


def read_controls(adapter_dir: str) -> list[Control]:
    """The "controls" list from device.json (or device.yaml) in an adapter's package, or []."""
    for name in ("device.json", "device.yaml"):
        path = os.path.join(adapter_dir, name)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            if name.endswith(".json"):
                device = cast(object, json.load(f))
            else:
                device = cast(object, yaml.safe_load(f))
        if not isinstance(device, dict):
            return []
        controls = cast(dict[str, object], device).get("controls")
        if not isinstance(controls, list):
            return []
        return [cast(Control, c) for c in cast(list[object], controls) if isinstance(c, dict)]
    return []


def as_number(value: object) -> float | None:
    """value as a float, or None when it is not a number (bools are not numbers here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _narrow(control: Control, limit: object) -> Control:
    """The control with the instance's min/max, which may only tighten the adapter's own range."""
    metric = control["metric"]
    if control.get("type") != "number" or not isinstance(limit, dict):
        raise ValueError(f"control_limits for {metric} need a number control and min/max keys")
    narrowed = dict(control)
    for key, value in cast(dict[str, object], limit).items():
        bound = as_number(value)
        if key not in ("min", "max") or bound is None:
            raise ValueError(f"control_limits for {metric}: {key} must be min or max with a number")
        adapter_bound = as_number(control.get(key))
        if adapter_bound is not None and (
            (key == "min" and bound < adapter_bound) or (key == "max" and bound > adapter_bound)
        ):
            raise ValueError(
                f"control_limits for {metric}: {key} {bound} is outside the adapter's {key} {adapter_bound}"
            )
        narrowed[key] = bound
    return narrowed


def apply_limits(controls: list[Control], limits: dict[str, object]) -> list[Control]:
    """Controls with an instance's control_limits applied; ValueError for limits that do not fit."""
    known = {str(c.get("metric")) for c in controls}
    unknown = sorted(set(limits) - known)
    if unknown:
        raise ValueError(f"control_limits for undeclared controls: {', '.join(unknown)}")
    result: list[Control] = []
    for control in controls:
        metric = str(control.get("metric"))
        if metric in limits:
            result.append(_narrow(control, limits[metric]))
        else:
            result.append(control)
    return result


def _check_number(control: Control, value: object) -> None:
    number = as_number(value)
    if number is None:
        raise ValueError(f"{control['metric']} needs a number, got {value!r}")
    low = as_number(control.get("min"))
    high = as_number(control.get("max"))
    if low is not None and number < low:
        raise ValueError(f"{control['metric']} = {number} is below its minimum {low}")
    if high is not None and number > high:
        raise ValueError(f"{control['metric']} = {number} is above its maximum {high}")


def _metric_and_value(data: str) -> tuple[object, object]:
    """tags.metric and fields.value of a LeafPoint control message."""
    point = cast(object, json.loads(data))
    if not isinstance(point, dict):
        raise ValueError("a control message must be a LeafPoint JSON object")
    point_dict = cast(dict[str, object], point)
    tags = point_dict.get("tags")
    fields = point_dict.get("fields")
    if not isinstance(tags, dict) or not isinstance(fields, dict):
        raise ValueError("a control message needs tags and fields")
    return cast(dict[str, object], tags).get("metric"), cast(dict[str, object], fields).get("value")


def check_control(controls: list[Control], data: str) -> None:
    """Raise ValueError unless the LeafPoint in data sets a declared metric to an allowed value."""
    if not controls:
        return
    metric, value = _metric_and_value(data)
    control = next((c for c in controls if c.get("metric") == metric), None)
    if control is None:
        raise ValueError(f"{metric!r} is not a declared control")
    if value is not None and value == control.get("reset"):
        return
    kind = control.get("type")
    if kind == "number":
        _check_number(control, value)
    elif kind == "choice":
        options = control.get("options")
        if not isinstance(options, list) or value not in cast(list[object], options):
            raise ValueError(f"{metric} cannot be set to {value!r}")
    elif not isinstance(value, str) or not value:
        raise ValueError(f"{metric} needs a text value")


def _part(point: dict[str, object], key: str) -> dict[str, object]:
    """A copy of point[key] when it is a dict, else an empty dict."""
    part = point.get(key)
    if isinstance(part, dict):
        return dict(cast(dict[str, object], part))
    return {}


def _field_value(value: object) -> int | float | str:
    """value as a LeafPoint field allows it: a number or text, anything else as its JSON."""
    if isinstance(value, (int, float, str)):
        return value
    return json.dumps(value)


def result_record(data: str, source: str, error: Exception | None = None) -> dict[str, object]:
    """
    A control message as the LeafPoint LEAF publishes on <control topic>/result, so that what was
    sent to the equipment is stored with the measurements.

    source ("ui" or "mqtt"), status ("applied" or "rejected") and a rejection's "error" are tags,
    for consumers to filter on. Built as a leafobject LeafPoint, so tags are text and there is
    always a field: a message without fields keeps its raw text in "message".
    """
    point: dict[str, object] = {}
    try:
        parsed = cast(object, json.loads(data))
        if isinstance(parsed, dict):
            point = cast(dict[str, object], parsed)
    except ValueError:
        pass
    tags: dict[str, str] = {}
    for key, value in _part(point, "tags").items():
        tags[key] = str(value)
    fields: dict[str, int | float | str] = {}
    for key, value in _part(point, "fields").items():
        fields[key] = _field_value(value)
    tags["source"] = source
    tags["status"] = "applied"
    if error is not None:
        tags["status"] = "rejected"
        tags["error"] = str(error)
    if not fields:
        fields["message"] = data
    record = LeafPoint()
    record.set_measurement(str(point.get("measurement", "control")))
    record.set_tags(tags)
    record.set_fields(fields)
    return {**record.to_json()}
