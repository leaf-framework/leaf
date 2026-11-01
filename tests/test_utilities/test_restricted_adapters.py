import asyncio
import logging
import subprocess

import pytest
from nicegui import ui

from leaf.ui import utils
from leaf.ui.utils import install_adapter, with_credentials

RESTRICTED = {
    "name": "LEAF-RAMSMART",
    "adapter_id": "RAMSMART",
    "repo_url": "https://git.wur.nl/leaf/adapters/leaf-ramsmart.git",
    "access": "restricted",
}


class PipRecorder:
    """Stands in for _run_pip: records each call and reports success."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")


def no_notify(*_args: object, **_kwargs: object) -> None:
    pass


def test_credentials_go_into_the_url_encoded() -> None:
    url = with_credentials("https://git.example.org:8443/group/repo.git", "deploy-1", "t@k:en/")
    assert url == "https://deploy-1:t%40k%3Aen%2F@git.example.org:8443/group/repo.git"


def test_restricted_install_uses_the_token_and_never_logs_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pip = PipRecorder()
    monkeypatch.setattr(utils, "_run_pip", pip)
    # ui.notify needs a browser client; the test only cares what pip gets
    monkeypatch.setattr(ui, "notify", no_notify)
    monkeypatch.delenv(utils.ADAPTER_INSTALL_DISABLE_ENV, raising=False)
    caplog.set_level(logging.DEBUG)
    asyncio.run(install_adapter(RESTRICTED, ("deploy-1", "secret-token")))
    assert pip.calls[0][-1] == "git+https://deploy-1:secret-token@git.wur.nl/leaf/adapters/leaf-ramsmart.git"
    assert "Installed LEAF-RAMSMART" in caplog.text
    assert "secret-token" not in caplog.text
