"""Wizard that builds an OUTPUTS entry from an output module's constructor, so the form always matches the code."""

import inspect
import os
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, Union, cast, get_args, get_origin

import yaml
from nicegui import ui

from leaf.modules.output_modules.output_module import OutputModule
from leaf.registry.discovery import discover_entry_point_equipment, discover_output_modules, output_module_dir
from leaf.utility.config_utils import store_secret

# LEAF passes these itself; a user never sets them.
SKIPPED = {"error_holder", "external_watcher", "instance_data", "output"}
# Masked in the form and moved to secrets.env, so the configuration only holds ${VAR}.
# A class adds its own with a SECRET_FIELDS attribute, e.g. SECRET_FIELDS = {"private_key"}.
SECRET_FIELDS = {"password"}
# A docstring argument, with or without its type: "port (int): The port number." or "port: The port number."
# Help text is required, so section headers such as "Args:" do not count.
DOC_ARG = re.compile(r"^\s*(\w+)\s*(?:\([^)]*\))?:\s*(\S.*)$")


@dataclass
class Field:
    name: str
    kind: type
    default: Any
    required: bool
    help: str = ""
    choices: list[str] = field(default_factory=list)
    secret: bool = False


def _own_docs(klass: type) -> dict[str, str]:
    """Argument name to its help line, from this class's own docstrings only."""
    # Only the class's own __init__; an inherited one would repeat the base docs.
    # Some classes document their arguments in the class docstring instead.
    init_doc: str | None = getattr(klass.__dict__.get("__init__"), "__doc__", None)
    class_doc: str | None = klass.__dict__.get("__doc__")
    lines: list[str] = []
    for doc in (init_doc, class_doc):
        if doc is not None:
            lines += doc.splitlines()
    docs: dict[str, str] = {}
    for line in lines:
        match = DOC_ARG.match(line)
        if match is None:
            continue
        if match.group(1) in docs:
            continue
        docs[match.group(1)] = match.group(2)
    return docs


def _documented(cls: type) -> dict[str, str]:
    """Argument name to its first help line, from the constructor docstrings; a subclass overrides its base."""
    docs: dict[str, str] = {}
    # Base classes document the arguments they share (fallback, name), so walk the MRO
    for klass in cls.__mro__:
        for name, help_line in _own_docs(klass).items():
            if name not in docs:
                docs[name] = help_line
    return docs


def _union_type(hint: Any) -> tuple[type | None, list[str]]:
    """The first type in the union a field can hold, so list[str] | str still gives a text field."""
    for arg in get_args(hint):
        if arg is NoneType:
            continue
        kind, choices = _base_type(arg)
        if kind is not None:
            return kind, choices
    return None, []


def _base_type(hint: Any) -> tuple[type | None, list[str]]:
    """The type a form field can hold, without None; a Literal gives its choices. None when no field fits."""
    origin = get_origin(hint)
    if origin is Literal:
        return str, [str(choice) for choice in get_args(hint)]
    if origin in (Union, UnionType):
        return _union_type(hint)
    # Without a type hint, or typed Any, text is the safe guess
    if hint is None or hint is Any:
        return str, []
    if hint in (str, int, float, bool):
        return hint, []
    if origin is list and get_args(hint) == (str,):
        return list, []
    if isinstance(hint, type) and issubclass(hint, OutputModule):
        return OutputModule, []
    return None, []


def form_fields(cls: type) -> list[Field]:
    """The constructor parameters a user can fill in, with their type, default and help."""
    try:
        hints = typing.get_type_hints(cls.__init__)
    except (NameError, TypeError):
        # An installed adapter can annotate with names that do not resolve here; fall back to text fields
        hints = {}
    docs = _documented(cls)
    # Only an adapter that documents its own arguments lists what users set; base-class docs alone do not
    lists_own = bool(_own_docs(cls))
    secrets = SECRET_FIELDS | set(getattr(cls, "SECRET_FIELDS", ()))
    fields: list[Field] = []
    for name, param in inspect.signature(cls).parameters.items():
        if name in SKIPPED:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        required = param.default is inspect.Parameter.empty
        # A class that documents its arguments lists what users set; an undocumented optional one is
        # internal or removed. A required one always shows, or the form could never be complete.
        if lists_own and name not in docs and not required:
            continue
        kind, choices = _base_type(hints.get(name))
        if kind is None:
            continue
        default = None
        if not required:
            default = param.default
        fields.append(Field(name, kind, default, required, docs.get(name, ""), choices, name in secrets))
    return fields


def _lines(value: object) -> list[str]:
    """A list field holds one item per line; blank lines are dropped."""
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _set_values(fields: list[Field], values: dict[str, Any]) -> dict[str, Any]:
    """The values a user filled in; those left at their default are left out to keep the config short."""
    entry: dict[str, Any] = {}
    for f in fields:
        value = values.get(f.name)
        if value is None or value == "":
            continue
        # ui.number hands back a float
        if f.kind is int:
            value = int(value)
        if f.kind is list:
            value = _lines(value)
            if not value:
                continue
        if value == f.default and not f.required:
            continue
        entry[f.name] = value
    return entry


def output_entry(code: str, fields: list[Field], values: dict[str, Any]) -> str:
    """YAML list item for OUTPUTS."""
    return yaml.safe_dump([{"plugin": code, **_set_values(fields, values)}], sort_keys=False)


def equipment_entry(code: str, data: dict[str, Any], fields: list[Field], values: dict[str, Any]) -> str:
    """YAML list item for EQUIPMENT_INSTANCES."""
    equipment: dict[str, Any] = {"adapter": code, "data": _set_values(DATA_FIELDS, data)}
    requirements = _set_values(fields, values)
    if requirements:
        equipment["requirements"] = requirements
    return yaml.safe_dump([{"equipment": equipment}], sort_keys=False)


def _item_indent(lines: list[str]) -> str:
    """Indentation of the first list item below a key, or two spaces when it has none yet."""
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            return line[: len(line) - len(stripped)]
        break
    return "  "


def insert_item(config: str, section: str, entry: str) -> str:
    """Config with entry as the first item of section; edits the text so comments survive, unlike a YAML round trip."""
    lines = config.splitlines()
    for i, line in enumerate(lines):
        key = line.split("#")[0].rstrip()
        if key not in (f"{section}:", f"{section}: []"):
            continue
        indent = _item_indent(lines[i + 1 :])
        item = [indent + entry_line for entry_line in entry.splitlines()]
        # An empty "[]" list becomes a block list, or the items would be a second value
        return "\n".join(lines[:i] + [f"{section}:"] + item + lines[i + 1 :]) + "\n"
    item = ["  " + entry_line for entry_line in entry.splitlines()]
    return config.rstrip("\n") + f"\n\n{section}:\n" + "\n".join(item) + "\n"


def _output_modules() -> dict[str, type[OutputModule]]:
    names = {file[:-3] for file in os.listdir(output_module_dir) if file.endswith(".py")}
    return dict(discover_output_modules(names))


def _list_input(f: Field, label: str) -> ui.element:
    """Multi-line box, one list item per line."""
    default: object = f.default
    lines = ""
    if isinstance(default, list):
        lines = "\n".join(str(item) for item in cast(list[object], default))
    return ui.textarea(label, value=lines, placeholder="One per line").classes("w-full")


def _field_input(f: Field, configured: list[str]) -> ui.element:
    label = f.name
    if f.required:
        label += " *"
    if f.kind is bool:
        element = ui.switch(label, value=bool(f.default))
    elif f.choices:
        element = ui.select(f.choices, label=label, value=f.default).classes("w-full")
    elif f.kind is OutputModule:
        # A fallback is another output in this configuration, named by its name or plugin
        element = ui.select(configured, label=label, clearable=True).classes("w-full")
    elif f.kind in (int, float):
        element = ui.number(label, value=f.default).classes("w-full")
    elif f.kind is list:
        element = _list_input(f, label)
    elif f.secret:
        element = ui.input(label, password=True, password_toggle_button=True).classes("w-full")
    else:
        element = ui.input(label, value=f.default).classes("w-full")
    if f.help:
        ui.label(f.help).classes("text-xs text-body-secondary -mt-1")
    if f.secret:
        ui.label("Stored in secrets.env next to the configuration; the configuration only gets ${VAR}.").classes(
            "text-xs text-body-secondary -mt-1"
        )
    if f.name == "filename" and isinstance(element, ui.input):
        _path_preview(element)
    return element


def _path_preview(element: ui.input) -> None:
    """Show where a file lands: the path is on the LEAF machine, which need not be the one with the browser."""
    where = ui.label().classes("text-xs text-body-secondary -mt-1")

    def show() -> None:
        value = element.value
        if not value:
            where.text = ""
            return
        where.text = f"On the LEAF machine: {os.path.abspath(value)}"

    _ = element.on_value_change(show)
    show()


def _store_secrets(config_path: Path, code: str, fields: list[Field], values: dict[str, Any]) -> None:
    """Move typed secrets to secrets.env; a ${VAR} the user typed stays as it is."""
    for f in fields:
        if not f.secret:
            continue
        value = values.get(f.name)
        if not value:
            continue
        if str(value).startswith("${"):
            continue
        values[f.name] = store_secret(config_path, f"LEAF_{code.upper()}_{f.name.upper()}", str(value))


def _section(config: str, section: str) -> list[Any]:
    """The items of a top-level list in the config; empty while the YAML does not parse."""
    try:
        parsed = yaml.safe_load(config)
    except yaml.YAMLError:
        return []
    if not isinstance(parsed, dict):
        return []
    items = parsed.get(section)
    if not isinstance(items, list):
        return []
    return items


def configured_outputs(config: str) -> list[str]:
    """How each output in the config is referred to: its name, or its plugin when it has none."""
    found: list[str] = []
    for entry in _section(config, "OUTPUTS"):
        if not isinstance(entry, dict):
            continue
        key = _output_key(entry.get("name"), entry.get("plugin"))
        if key:
            found.append(key)
    return found


def _output_key(name: Any, plugin: Any) -> str:
    """Matches how LEAF tells outputs apart: by name, by plugin when unnamed."""
    if name:
        return str(name)
    if plugin:
        return str(plugin)
    return ""


def configured_instances(config: str) -> list[str]:
    """The instance_id of each equipment instance in the config."""
    found: list[str] = []
    for entry in _section(config, "EQUIPMENT_INSTANCES"):
        if not isinstance(entry, dict):
            continue
        equipment = entry.get("equipment")
        if not isinstance(equipment, dict):
            continue
        data = equipment.get("data")
        if isinstance(data, dict) and data.get("instance_id"):
            found.append(str(data["instance_id"]))
    return found


def _missing(fields: list[Field], values: dict[str, Any]) -> str | None:
    missing: list[str] = []
    for f in fields:
        if f.required and values.get(f.name) in (None, ""):
            missing.append(f.name)
    if missing:
        return f"Fill in {', '.join(missing)}"
    return None


def form_problem(fields: list[Field], values: dict[str, Any], code: str, configured: list[str]) -> str | None:
    """Why the output form cannot be added yet, or None."""
    missing = _missing(fields, values)
    if missing is not None:
        return missing
    key = _output_key(values.get("name"), code)
    taken: list[str] = []
    for existing in configured:
        taken.append(existing.lower())
    if key.lower() in taken:
        return f"There already is an output called {key}: give this one a different name"
    return None


def open_output_wizard(editor: ui.codemirror, config_path: Path) -> None:
    """Dialog that adds an output to the editor; saving stays with the editor's own button."""
    modules = _output_modules()
    codes = sorted(modules)
    configured = configured_outputs(editor.value)
    inputs: dict[str, ui.element] = {}

    with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
        ui.label("Add output").classes("text-lg font-semibold text-heading")
        plugin = ui.select(codes, label="Output module", value=codes[0]).classes("w-full")
        form = ui.column().classes("w-full gap-2")

        def build_form() -> None:
            form.clear()
            inputs.clear()
            with form:
                for f in form_fields(modules[plugin.value]):
                    inputs[f.name] = _field_input(f, configured)

        def add() -> None:
            fields = form_fields(modules[plugin.value])
            values = {name: getattr(element, "value", None) for name, element in inputs.items()}
            problem = form_problem(fields, values, plugin.value, configured)
            if problem is not None:
                ui.notify(problem, color="warning")
                return
            _store_secrets(config_path, plugin.value, fields, values)
            editor.value = insert_item(editor.value, "OUTPUTS", output_entry(plugin.value, fields, values))
            ui.notify(f"Added {plugin.value} output, review it and press Save & Restart", color="positive")
            dialog.close()

        _ = plugin.on_value_change(lambda _: build_form())
        build_form()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Add to configuration", icon="add", on_click=add).classes("btn-primary")

    dialog.on("hide", dialog.delete)
    dialog.open()


# The instance data every adapter needs (leaf/register/equipment_data.yaml) and the optional topic root;
# adapter_id comes from the adapter
DATA_FIELDS = [
    Field("instance_id", str, None, True, "Unique name of this device; part of its MQTT topics."),
    Field("organisation", str, None, True, "Organisation in the topic path, e.g. wur."),
    Field("department", str, None, True, "Department in the topic path, e.g. ssb."),
    Field("root", str, None, False, "Optional first part of every topic, e.g. leaf; empty starts at organisation."),
]


def equipment_problem(
    fields: list[Field], data: dict[str, Any], values: dict[str, Any], configured: list[str]
) -> str | None:
    """Why the equipment form cannot be added yet, or None."""
    missing = _missing(DATA_FIELDS + fields, {**values, **data})
    if missing is not None:
        return missing
    if data["instance_id"] in configured:
        return f"There already is a device with instance_id {data['instance_id']}"
    return None


def open_equipment_wizard(editor: ui.codemirror, config_path: Path) -> None:
    """Dialog that adds an equipment instance to the editor, with the adapter's requirements as fields."""
    adapters: dict[str, type] = {}
    for code, cls, _ in discover_entry_point_equipment():
        adapters[code] = cls
    if not adapters:
        ui.notify("No adapters installed", color="warning")
        return
    codes = sorted(adapters)
    configured = configured_instances(editor.value)
    data_inputs: dict[str, ui.element] = {}
    inputs: dict[str, ui.element] = {}

    with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
        ui.label("Add equipment").classes("text-lg font-semibold text-heading")
        adapter = ui.select(codes, label="Adapter", value=codes[0], with_input=True).classes("w-full")
        for f in DATA_FIELDS:
            data_inputs[f.name] = _field_input(f, [])
        ui.label("Requirements").classes("font-semibold text-heading mt-2")
        form = ui.column().classes("w-full gap-2")

        def build_form() -> None:
            form.clear()
            inputs.clear()
            with form:
                for f in form_fields(adapters[adapter.value]):
                    inputs[f.name] = _field_input(f, [])

        def add() -> None:
            fields = form_fields(adapters[adapter.value])
            data = {name: getattr(element, "value", None) for name, element in data_inputs.items()}
            values = {name: getattr(element, "value", None) for name, element in inputs.items()}
            problem = equipment_problem(fields, data, values, configured)
            if problem is not None:
                ui.notify(problem, color="warning")
                return
            _store_secrets(config_path, adapter.value, fields, values)
            entry = equipment_entry(adapter.value, data, fields, values)
            editor.value = insert_item(editor.value, "EQUIPMENT_INSTANCES", entry)
            ui.notify(f"Added {data['instance_id']}, review it and press Save & Restart", color="positive")
            dialog.close()

        _ = adapter.on_value_change(lambda _: build_form())
        build_form()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Add to configuration", icon="add", on_click=add).classes("btn-primary")

    dialog.on("hide", dialog.delete)
    dialog.open()
