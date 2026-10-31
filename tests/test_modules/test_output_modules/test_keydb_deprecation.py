import pytest

from leaf.modules.output_modules import keydb
from leaf.modules.output_modules.keydb import DEPRECATION_MESSAGE, KEYDB


class WarningRecorder:
    """Stands in for the module logger's warning: records each message."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)


def no_connect(_self: KEYDB) -> None:
    pass


def test_keydb_warns_that_it_is_deprecated(monkeypatch: pytest.MonkeyPatch) -> None:
    warning = WarningRecorder()
    # No server needed: the warning is given before the module connects
    monkeypatch.setattr(KEYDB, "connect", no_connect)
    monkeypatch.setattr(keydb.logger, "warning", warning)
    _ = KEYDB(host="localhost")
    assert warning.messages == [DEPRECATION_MESSAGE]
