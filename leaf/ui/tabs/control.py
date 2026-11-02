"""
LEAF Control tab: a form per running instance with ``control: true``.

The form comes from the ``controls`` list in the adapter's device.json. Each control sets a
metric to a value and is sent to the controller as a LeafPoint (tags.metric, fields.value):

    {"metric": "T_sp", "label": "Temperature setpoint", "type": "number", "reset": "recipe"}
    {"metric": "batch", "type": "choice", "options": ["paused", "running", "aborted"],
     "confirm": ["aborted"], "fields": [{"name": "reason", "type": "text", "required": false}]}

type is "number", "choice" (one button per option) or "text". Optional keys: label, unit,
reset (an extra button sending that value), confirm (values that ask first) and fields
(extra fields sent next to "value", each "text" or "number").
"""

import json
import time
from collections.abc import Awaitable, Callable
from typing import cast

from nicegui import run, ui

from leaf.adapters.control_spec import Control, as_number
from leaf.adapters.equipment_adapter import EquipmentAdapter
from leaf.register.metadata import MetadataManager
from leaf.ui.components.app_control import confirm
from leaf.utility.logger.logger_utils import get_logger
from leaf.utility.running_adapters import adapters as running_adapters
from leaf.utility.running_adapters import startup_done

logger = get_logger(__name__, log_file="interface.log")


def parse_value(kind: str, raw: object, options: list[str]) -> float | str:
    """The value to send for a form input; ValueError carries a message for the user."""
    if kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("enter a number")
        return float(raw)
    if kind == "choice":
        if raw not in options:
            raise ValueError(f"choose one of {', '.join(options)}")
        return str(raw)
    if kind == "text":
        if raw is None or raw == "":
            raise ValueError("enter a value")
        return str(raw)
    raise ValueError(f"unknown control type {kind!r}")


def parse_fields(fields: list[Control], raw: dict[str, object]) -> dict[str, float | str]:
    """Extra fields to send; empty optional ones are left out."""
    parsed: dict[str, float | str] = {}
    for field in fields:
        name = str(field["name"])
        value = raw.get(name)
        if value is None or value == "":
            if field.get("required", True):
                raise ValueError(f"{name} is required")
            continue
        parsed[name] = parse_value(str(field.get("type", "text")), value, [])
    return parsed


def control_point(
    metadata: MetadataManager, metric: str, value: float | str, fields: dict[str, float | str]
) -> dict[str, object]:
    """LeafPoint JSON setting metric to value, tagged like the instance's measurements."""
    instance = cast(dict[str, object], metadata.get_instance_data())
    tags = {key: str(v) for key, v in instance.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)}
    tags["metric"] = metric
    return {
        "measurement": metadata.get_equipment_data("adapter_id"),
        "tags": tags,
        "fields": {"value": value, **fields},
        "timestamp": time.time(),
    }


def _options(control: Control, key: str) -> list[str]:
    values = control.get(key)
    if not isinstance(values, list):
        return []
    return [str(v) for v in cast(list[object], values)]


def _fields(control: Control) -> list[Control]:
    raw = control.get("fields")
    if not isinstance(raw, list):
        return []
    return [cast(Control, f) for f in cast(list[object], raw) if isinstance(f, dict)]


Send = Callable[[object, str], Awaitable[None]]


def range_hint(low: float | None, high: float | None) -> str:
    """The limits of a number control as shown under its input, e.g. "295 to 305", or ""."""
    if low is not None and high is not None:
        return f"{low:g} to {high:g}"
    if low is not None:
        return f"from {low:g}"
    if high is not None:
        return f"up to {high:g}"
    return ""


def _value_widgets(control: Control, kind: str, send: Send) -> None:
    """One button per option for a choice, otherwise an input plus a Set button."""
    metric = str(control["metric"])
    if kind == "choice":
        for option in _options(control, "options"):
            _ = ui.button(option, on_click=lambda o=option: send(o, kind)).props("outline").classes("btn-secondary")
        return
    if kind == "number":
        low = as_number(control.get("min"))
        high = as_number(control.get("max"))
        # LEAF rejects out-of-range values anyway; the input bounds and hint just say so up front
        hint = range_hint(low, high)
        value_input: ui.input | ui.number = ui.number(
            label=metric, suffix=str(control.get("unit", "")), min=low, max=high
        ).classes("w-40")
        if hint:
            _ = value_input.props(f'hint="{hint}"')
    else:
        value_input = ui.input(label=metric).classes("w-60")
    _ = ui.button("Set", icon="send", on_click=lambda: send(value_input.value, kind)).classes("btn-primary")


def _field_widgets(fields: list[Control]) -> dict[str, ui.input | ui.number]:
    """Inputs for the extra fields sent next to the value, e.g. an abort reason."""
    inputs: dict[str, ui.input | ui.number] = {}
    for field in fields:
        name = str(field["name"])
        label = name
        if not field.get("required", True):
            label = f"{name} (optional)"
        if field.get("type") == "number":
            inputs[name] = ui.number(label=label).classes("w-40")
        else:
            inputs[name] = ui.input(label=label).classes("w-60")
    return inputs


def _control_row(adapter: EquipmentAdapter, control: Control) -> None:
    """One labelled row: the value input or option buttons, a reset button, then any extra fields."""
    metric = str(control["metric"])
    label = str(control.get("label", metric))
    options = _options(control, "options")
    needs_confirm = _options(control, "confirm")
    fields = _fields(control)
    field_inputs: dict[str, ui.input | ui.number] = {}

    async def deliver(value: float | str, extra: dict[str, float | str]) -> None:
        point = control_point(adapter.metadata_manager, metric, value, extra)
        try:
            # The controller usually makes a blocking HTTP call
            await run.io_bound(adapter.send_control, json.dumps(point))
            ui.notify(f"{label}: {value} sent", type="positive")
        except Exception as e:
            logger.error(f"Control {metric}={value} failed: {e}")
            ui.notify(f"{label}: {e}", type="negative", close_button=True, timeout=8000)

    async def send(raw: object, value_kind: str) -> None:
        try:
            value = parse_value(value_kind, raw, options)
            extra = parse_fields(fields, {name: field_input.value for name, field_input in field_inputs.items()})
        except ValueError as e:
            ui.notify(f"{label}: {e}", type="warning")
            return
        if str(value) not in needs_confirm:
            await deliver(value, extra)
            return
        text = f"Sets {metric} to {value} on this instance."
        confirm(f"{label}: {value}?", text, str(value), "warning", "btn-danger", lambda: deliver(value, extra))

    with ui.row().classes("w-full items-center gap-3 py-1"):
        _ = ui.label(label).classes("w-48 font-medium").tooltip(metric)
        _value_widgets(control, str(control.get("type", "text")), send)
        reset = control.get("reset")
        if isinstance(reset, str):
            _ = ui.button(reset, on_click=lambda: send(reset, "text")).props("flat")
        field_inputs.update(_field_widgets(fields))


def controllable_instances() -> list[EquipmentAdapter]:
    """Running instances with a controller, i.e. started with control: true."""
    return [a for a in cast(list[object], running_adapters) if isinstance(a, EquipmentAdapter) and a.has_controller()]


def _instance_card(adapter: EquipmentAdapter) -> None:
    metadata = adapter.metadata_manager
    title = f"{metadata.get_instance_id()} ({metadata.get_equipment_data('adapter_id')})"
    # Foldable, so an instance with many controls can be tucked away
    with (
        ui.card().classes("leaf-card w-full mb-4"),
        ui.expansion(title, caption=f"{len(adapter.controls)} controls", value=True)
        .classes("w-full")
        .props('header-class="text-lg font-semibold text-heading"'),
    ):
        if not adapter.controls:
            _ = ui.label(
                "This adapter declares no controls in its device.json; send LeafPoints on the control topic instead."
            ).classes("text-body-secondary")
        # Two columns on wide screens, one on narrow ones
        with ui.element("div").classes("grid grid-cols-1 lg:grid-cols-2 gap-x-8 w-full"):
            for control in adapter.controls:
                _control_row(adapter, control)


def create_control_tab(control_tab: ui.tab) -> None:
    """
    One card per running instance that has a controller; the tab is hidden while there are none.

    Adapters start a few seconds after the UI, so a page built earlier checks until startup is done.
    """
    with ui.tab_panel(control_tab).classes("w-full p-6"):
        with ui.row().classes("items-center mb-6"):
            _ = ui.icon("tune", size="2rem").classes("text-icon")
            _ = ui.label("Control").classes("text-2xl font-bold text-heading ml-2")
        cards = ui.column().classes("w-full")

    shown: list[EquipmentAdapter] = []

    def refresh() -> None:
        instances = controllable_instances()
        _ = control_tab.set_visibility(bool(instances))
        # Rebuild only when the instances change, so typed values are not wiped every refresh
        if instances == shown:
            return
        shown[:] = instances
        _ = cards.clear()
        with cards:
            for adapter in instances:
                _instance_card(adapter)

    refresh()
    if startup_done.is_set():
        return

    def refresh_until_started() -> None:
        # Read the flag first, so instances started just before it was set are still picked up
        done = startup_done.is_set()
        refresh()
        if done:
            timer.cancel()

    timer = ui.timer(1.0, refresh_until_started)
