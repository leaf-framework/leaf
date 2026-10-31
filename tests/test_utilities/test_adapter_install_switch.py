import asyncio
import subprocess

import pytest
from nicegui import ui

from leaf.ui import utils
from leaf.ui.utils import ADAPTER_INSTALL_DISABLE_ENV, adapter_install_disabled, install_adapter, uninstall_adapter

ADAPTER = {"name": "leaf-example", "adapter_id": "Example", "repo_url": "https://example.org/leaf-example.git"}


class PipRecorder:
    """Stands in for _run_pip: records each call and reports success."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")


def no_notify(*_args: object, **_kwargs: object) -> None:
    pass


@pytest.fixture
def pip(monkeypatch: pytest.MonkeyPatch) -> PipRecorder:
    recorder = PipRecorder()
    monkeypatch.setattr(utils, "_run_pip", recorder)
    # ui.notify needs a browser client; the tests only care whether pip runs
    monkeypatch.setattr(ui, "notify", no_notify)
    return recorder


@pytest.mark.parametrize("value, disabled", [("1", True), ("true", True), (" YES ", True), ("0", False), ("", False)])
def test_switch_values(monkeypatch: pytest.MonkeyPatch, value: str, disabled: bool) -> None:
    monkeypatch.setenv(ADAPTER_INSTALL_DISABLE_ENV, value)
    assert adapter_install_disabled() is disabled


def test_disabled_install_and_uninstall_never_run_pip(monkeypatch: pytest.MonkeyPatch, pip: PipRecorder) -> None:
    monkeypatch.setenv(ADAPTER_INSTALL_DISABLE_ENV, "1")
    asyncio.run(install_adapter(ADAPTER))
    asyncio.run(uninstall_adapter(ADAPTER))
    assert pip.calls == []


def test_enabled_install_and_uninstall_run_pip(monkeypatch: pytest.MonkeyPatch, pip: PipRecorder) -> None:
    monkeypatch.delenv(ADAPTER_INSTALL_DISABLE_ENV, raising=False)
    asyncio.run(install_adapter(ADAPTER))
    asyncio.run(uninstall_adapter(ADAPTER))
    assert [call[0] for call in pip.calls][0] == "install"
    assert pip.calls[-1] == ("uninstall", "-y", "leaf-example")
