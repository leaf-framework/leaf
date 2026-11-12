import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from leaf.modules.output_modules.file import FILE
from leaf.modules.output_modules.mqtt import MQTT
from leaf.modules.output_modules.output_module import OutputModule
from leaf.ui.components.config_wizard import (
    _store_secrets,
    configured_instances,
    configured_outputs,
    equipment_entry,
    equipment_problem,
    form_fields,
    form_problem,
    insert_item,
    output_entry,
)
from leaf.utility.config_utils import SECRETS_FILE, load_secrets, substitute_in_config


def test_mqtt_fields() -> None:
    fields = {f.name: f for f in form_fields(MQTT)}
    assert fields["broker"].required
    assert fields["port"].kind is int
    assert fields["port"].default == 1883
    assert fields["protocol"].choices == ["v3", "v5"]
    assert fields["tls"].kind is bool
    assert fields["fallback"].kind is OutputModule
    assert "port number" in fields["port"].help
    # Set by LEAF, or removed and only kept so old configs still load
    assert "error_holder" not in fields
    assert "heartbeat_topic" not in fields


def test_help_from_base_class() -> None:
    fields = {f.name: f for f in form_fields(FILE)}
    assert fields["filename"].required
    assert "written to" in fields["filename"].help
    # name and fallback are documented once, on OutputModule
    assert "status page" in fields["name"].help
    assert fields["fallback"].help
    assert "error_holder" not in fields


def test_entry_leaves_defaults_out() -> None:
    values = {"broker": "mqtt.lab", "port": 8883.0, "tls": True, "protocol": "v3", "username": ""}
    entry = yaml.safe_load(output_entry("mqtt", form_fields(MQTT), values))
    assert entry == [{"plugin": "mqtt", "broker": "mqtt.lab", "port": 8883, "tls": True}]


def test_insert_keeps_comments_and_indent() -> None:
    config = "EQUIPMENT_INSTANCES: []\n\nOUTPUTS:\n    - plugin: mqtt\n      broker: localhost\n# MQTT output needs a broker\n"
    result = insert_item(config, "OUTPUTS", output_entry("file", form_fields(FILE), {"filename": "out.json"}))
    assert "# MQTT output needs a broker" in result
    assert yaml.safe_load(result)["OUTPUTS"] == [
        {"plugin": "file", "filename": "out.json"},
        {"plugin": "mqtt", "broker": "localhost"},
    ]


def test_insert_without_outputs_section() -> None:
    entry = output_entry("file", form_fields(FILE), {"filename": "a"})
    result = insert_item("EQUIPMENT_INSTANCES: []\n", "OUTPUTS", entry)
    assert yaml.safe_load(result)["OUTPUTS"] == [{"plugin": "file", "filename": "a"}]
    # An empty flow list becomes a block list with the item
    assert yaml.safe_load(insert_item("OUTPUTS: [] # none yet\n", "OUTPUTS", entry))["OUTPUTS"] == [
        {"plugin": "file", "filename": "a"}
    ]


def test_password_moves_to_secrets_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # store_secret also sets the variable; a copy keeps it out of the other tests
    monkeypatch.setattr(os, "environ", {})
    config = tmp_path / "configuration.yaml"
    first: dict[str, Any] = {"password": "koe#horst"}
    second: dict[str, Any] = {"password": "other"}
    typed: dict[str, Any] = {"password": "${MY_OWN}"}
    _store_secrets(config, "mqtt", form_fields(MQTT), first)
    _store_secrets(config, "mqtt", form_fields(MQTT), second)
    _store_secrets(config, "mqtt", form_fields(MQTT), typed)
    assert first["password"] == "${LEAF_MQTT_PASSWORD}"
    assert second["password"] == "${LEAF_MQTT_PASSWORD_2}"
    assert typed["password"] == "${MY_OWN}"
    secrets = tmp_path / SECRETS_FILE
    assert secrets.read_text() == "LEAF_MQTT_PASSWORD=koe#horst\nLEAF_MQTT_PASSWORD_2=other\n"
    assert secrets.stat().st_mode & 0o777 == 0o600


def test_load_secrets_keeps_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = (tmp_path / SECRETS_FILE).write_text("# wizard\nLEAF_A=from=file\nLEAF_B=file\n")
    monkeypatch.setattr(os, "environ", {"LEAF_B": "env"})
    load_secrets(tmp_path / "configuration.yaml")
    assert os.environ["LEAF_A"] == "from=file"
    assert os.environ["LEAF_B"] == "env"


@pytest.mark.parametrize("password", ["!abc", "a: b", "x #y", "*z", "koe#horst"])
def test_password_with_yaml_syntax(password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"LEAF_P": password, "LEAF_PORT": "8883"})
    config = substitute_in_config(yaml.safe_load("password: ${LEAF_P}\nport: ${LEAF_PORT}\nurl: http://${LEAF_PORT}\n"))
    assert config == {"password": password, "port": 8883, "url": "http://8883"}


def test_fallback_choices_and_duplicates() -> None:
    config = "OUTPUTS:\n  - plugin: MQTT\n    broker: localhost\n  - plugin: file\n    name: share\n    filename: a\n"
    configured = configured_outputs(config)
    assert configured == ["MQTT", "share"]
    fields = form_fields(MQTT)
    problem = form_problem(fields, {"broker": "cloud"}, "mqtt", configured)
    assert problem is not None
    assert "different name" in problem
    assert form_problem(fields, {"broker": "cloud", "name": "cloud"}, "mqtt", configured) is None
    assert form_problem(fields, {}, "mqtt", configured) == "Fill in broker"
    assert configured_outputs("OUTPUTS: [") == []


class _Adapter:
    """An adapter documented the short way.

    Args:
        device_addresses: Serial addresses of the devices, one per line.
        baudrate: Line speed.
        external_watcher: Set by LEAF, like instance_data and output.
    """

    def __init__(
        self,
        instance_data: dict[str, str],
        output: OutputModule,
        port,  # noqa: ANN001  untyped on purpose
        device_addresses: list[str] | str | None = None,
        baudrate: int = 9600,
        options: dict[str, str] | None = None,
        external_watcher: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        pass


def test_adapter_style_fields() -> None:
    fields = {f.name: f for f in form_fields(_Adapter)}
    # list[str] | str becomes a one-per-line list, help comes from "name: help" in the class docstring
    assert fields["device_addresses"].kind is list
    assert "Serial addresses" in fields["device_addresses"].help
    assert fields["baudrate"].help == "Line speed."
    # Required but undocumented and untyped: shown as text, or the form could never be complete
    assert fields["port"].required
    assert fields["port"].kind is str
    # Set by LEAF, optional and undocumented, not a form type, or *args/**kwargs: left out
    assert set(fields) == {"port", "device_addresses", "baudrate"}


def test_equipment_entry() -> None:
    config = "EQUIPMENT_INSTANCES:\n  - equipment:\n      adapter: Example\n      data:\n        instance_id: one\n\nOUTPUTS: []\n"
    configured = configured_instances(config)
    assert configured == ["one"]
    fields = form_fields(_Adapter)
    data = {"instance_id": "one", "organisation": "wur", "department": "ssb"}
    assert equipment_problem(fields, data, {"port": "/dev/tty"}, configured) == (
        "There already is a device with instance_id one"
    )
    assert equipment_problem(fields, {**data, "department": ""}, {}, configured) == "Fill in department, port"
    data["instance_id"] = "two"
    # An empty root is left out, so topics start at the organisation
    data["root"] = ""
    values = {"port": "/dev/tty", "baudrate": 9600.0, "device_addresses": ""}
    assert equipment_problem(fields, data, values, configured) is None
    result = yaml.safe_load(insert_item(config, "EQUIPMENT_INSTANCES", equipment_entry("Serial", data, fields, values)))
    assert result["EQUIPMENT_INSTANCES"][0] == {
        "equipment": {
            "adapter": "Serial",
            "data": {"instance_id": "two", "organisation": "wur", "department": "ssb"},
            "requirements": {"port": "/dev/tty"},
        }
    }
    assert len(result["EQUIPMENT_INSTANCES"]) == 2


class _Undocumented(_Adapter):
    # No docstring of its own, like an adapter whose base class documents the shared arguments
    def __init__(
        self,
        instance_data: dict[str, str],
        output: OutputModule,
        host: str,
        topics: list[str] | None = None,
        port: int = 4840,
    ) -> None:
        super().__init__(instance_data, output, host)


def test_list_field_and_undocumented_adapter() -> None:
    fields = form_fields(_Undocumented)
    # Base-class docs alone do not hide the optional arguments of an adapter without its own docstring
    assert [f.name for f in fields] == ["host", "topics", "port"]
    assert fields[1].kind is list
    entry = yaml.safe_load(output_entry("OPC", fields, {"host": "plc", "topics": "ns=2;s=a\n\n ns=2;s=b \n"}))
    assert entry == [{"plugin": "OPC", "host": "plc", "topics": ["ns=2;s=a", "ns=2;s=b"]}]
    # Only blank lines leave the list out
    assert yaml.safe_load(output_entry("OPC", fields, {"host": "plc", "topics": " \n"})) == [
        {"plugin": "OPC", "host": "plc"}
    ]


class _Login(_Adapter):
    # Adapter-level secrets, on top of the default password
    SECRET_FIELDS = {"private_key"}

    def __init__(
        self,
        instance_data: dict[str, str],
        output: OutputModule,
        host: str,
        username: str | None = None,
        password: str | None = None,
        private_key: str | None = None,
    ) -> None:
        super().__init__(instance_data, output, host)


def test_adapter_declares_secret_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    config = tmp_path / "configuration.yaml"
    fields = form_fields(_Login)
    assert [f.name for f in fields if f.secret] == ["password", "private_key"]
    values: dict[str, Any] = {"host": "plc", "username": "leaf", "password": "", "private_key": "/keys/leaf.pem"}
    _store_secrets(config, "OPC", fields, values)
    # The username stays readable, an empty field stays empty
    assert values == {"host": "plc", "username": "leaf", "password": "", "private_key": "${LEAF_OPC_PRIVATE_KEY}"}
    assert (tmp_path / SECRETS_FILE).read_text() == "LEAF_OPC_PRIVATE_KEY=/keys/leaf.pem\n"
