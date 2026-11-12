from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from requests import ConnectionError

from leaf.adapters.equipment_adapter import EquipmentAdapter
from leaf.modules.input_modules.http_watcher import HTTPWatcher
from leaf.modules.input_modules.opc_watcher import OPCWatcher
from leaf.utility.security import http_warnings, is_local, mqtt_warnings


def test_local_connections_are_never_flagged():
    assert is_local("localhost")
    assert is_local("/var/run/mosquitto.sock")
    assert not is_local("broker.example.org")
    assert mqtt_warnings("MQTT", "127.0.0.1", None, False) == []
    assert http_warnings("HTTP", "http://localhost:8080/data") == []


def test_mqtt_warnings():
    assert len(mqtt_warnings("MQTT", "broker.example.org", None, False)) == 2
    assert "password sent unencrypted" in mqtt_warnings("MQTT", "broker.example.org", "leaf", False)[0]
    assert mqtt_warnings("MQTT", "broker.example.org", "leaf", True) == []


def test_http_watcher_flags_plain_http_only():
    watcher = HTTPWatcher(MagicMock(), "http://10.0.4.12/data", start_url="https://10.0.4.12/start")
    assert watcher.security_warnings() == ["HTTP input to 10.0.4.12: plain http://, use https://"]


def test_opc_watcher_flags_missing_security_and_login():
    def opc(
        security: str | None = None,
        username: str | None = None,
        password: str | None = None,
        certificate: str | None = None,
    ) -> OPCWatcher:
        return OPCWatcher(
            MagicMock(),
            "plc.lab",
            4840,
            set(),
            [],
            username=username,
            password=password,
            security=security,
            certificate=certificate,
        )

    assert len(opc().security_warnings()) == 2
    assert (
        opc(security="Basic256Sha256,SignAndEncrypt,c.pem,k.pem", username="u", password="p").security_warnings() == []
    )
    assert opc(certificate="c.pem").security_warnings() == ["OPC UA to plc.lab: traffic unencrypted, set security"]


def test_disconnected_lists_parts_that_are_down():
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    watcher = MagicMock()
    watcher.is_connected.return_value = False
    output = MagicMock()
    output.is_connected.return_value = True
    adapter: Any = SimpleNamespace(_stop_event=stop_event, _watcher=watcher, _external_watcher=None, _output=output)
    assert EquipmentAdapter.disconnected(adapter) == ["MagicMock input"]

    # A stopped instance is not reported as down.
    stop_event.is_set.return_value = True
    assert EquipmentAdapter.disconnected(adapter) == []


def test_opc_watcher_is_not_connected_before_start():
    watcher = OPCWatcher(MagicMock(), "plc.lab", 4840, set(), [])
    assert not watcher.is_connected()


def test_http_watcher_is_down_while_a_url_fails():
    watcher = HTTPWatcher(MagicMock(), "http://typo.invalid/data")
    watcher._running = True  # pyright: ignore[reportPrivateUsage]
    with patch("leaf.modules.input_modules.http_watcher.requests.get", side_effect=ConnectionError("no such host")):
        _ = watcher._fetch_data()  # pyright: ignore[reportPrivateUsage]
    assert not watcher.is_connected()

    with patch("leaf.modules.input_modules.http_watcher.requests.get", return_value=MagicMock(status_code=304)):
        _ = watcher._fetch_data()  # pyright: ignore[reportPrivateUsage]
    assert watcher.is_connected()
