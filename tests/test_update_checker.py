"""Tests for the background PyPI update check."""

import asyncio
import json
from unittest.mock import patch

import pytest

from leaf.ui import update_checker
from leaf.ui.update_checker import (
    UpdateStatus,
    check_for_update,
    fetch_latest_version,
    is_newer,
    is_source_install,
    parse_version,
    start_update_checker,
    stop_update_checker,
)


@pytest.fixture(autouse=True)
def clean_status():
    """Give every test a fresh module-level status."""
    update_checker._status = UpdateStatus()
    yield
    update_checker._status = UpdateStatus()
    update_checker._task = None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.4.0", (1, 4, 0)),
        ("0.6", (0, 6)),
        ("10.0.12", (10, 0, 12)),
        ("1.4.0rc1", None),
        ("1.4.dev0", None),
        ("", None),
        ("not-a-version", None),
    ],
)
def test_parse_version(value, expected):
    assert parse_version(value) == expected


@pytest.mark.parametrize(
    "candidate,installed,expected",
    [
        ("0.7.0", "0.6.0", True),
        ("1.0.0", "0.9.9", True),
        ("0.6.1", "0.6.0", True),
        ("0.6.0", "0.6.0", False),
        ("0.5.0", "0.6.0", False),
        ("0.6", "0.6.0", False),  # padded, so equal
        ("0.7", "0.6.0", True),
    ],
)
def test_is_newer(candidate, installed, expected):
    assert is_newer(candidate, installed) is expected


def test_is_newer_ignores_unparseable_versions():
    """An ambiguous comparison must never produce an update prompt."""
    assert is_newer("1.0.0rc1", "0.6.0") is False
    assert is_newer("0.7.0", "0.6.0.dev3") is False


def test_is_newer_ignores_source_tree_fallback():
    """0.0.0 means the metadata is missing, not that every release is newer."""
    assert is_newer("0.7.0", update_checker.UNKNOWN_VERSION) is False


def test_check_for_update_flags_newer_release():
    async def fake_fetch():
        return "0.7.0"

    with (
        patch.object(update_checker, "__version__", "0.6.0"),
        patch.object(update_checker, "fetch_latest_version", side_effect=fake_fetch),
    ):
        status = asyncio.run(check_for_update())

    assert status.latest_version == "0.7.0"
    assert status.update_available is True
    assert status.last_checked is not None


def test_check_for_update_when_up_to_date():
    async def fake_fetch():
        return "0.6.0"

    with (
        patch.object(update_checker, "__version__", "0.6.0"),
        patch.object(update_checker, "fetch_latest_version", side_effect=fake_fetch),
    ):
        status = asyncio.run(check_for_update())

    assert status.latest_version == "0.6.0"
    assert status.update_available is False


def test_check_for_update_survives_unreachable_pypi():
    """A failed fetch leaves the status untouched rather than raising."""

    async def fake_fetch():
        return None

    with patch.object(update_checker, "fetch_latest_version", side_effect=fake_fetch):
        status = asyncio.run(check_for_update())

    assert status.latest_version is None
    assert status.update_available is False
    assert status.last_checked is None


def test_fetch_latest_version_handles_network_error():
    import httpx

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url):
            raise httpx.ConnectError("no network")

    with patch.object(update_checker.httpx, "AsyncClient", lambda **kwargs: FailingClient()):
        assert asyncio.run(fetch_latest_version()) is None


def test_first_check_is_delayed_by_an_hour():
    """The check must not run at startup, and must repeat weekly afterwards."""
    sleeps: list[float] = []
    checks = 0

    async def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    async def fake_check():
        nonlocal checks
        checks += 1

    async def run_loop():
        with (
            patch.object(update_checker.asyncio, "sleep", fake_sleep),
            patch.object(update_checker, "check_for_update", fake_check),
        ):
            with pytest.raises(asyncio.CancelledError):
                await update_checker._check_loop()

    asyncio.run(run_loop())

    assert sleeps[0] == update_checker.FIRST_CHECK_DELAY_SECONDS == 3600
    assert sleeps[1] == update_checker.RECHECK_INTERVAL_SECONDS == 7 * 24 * 3600
    assert sleeps[2] == update_checker.RECHECK_INTERVAL_SECONDS
    assert checks == 2  # one per completed sleep, never before the first


def test_check_loop_survives_a_failing_check():
    """One bad check must not kill the weekly schedule."""
    sleeps: list[float] = []
    checks = 0

    async def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    async def failing_check():
        nonlocal checks
        checks += 1
        raise RuntimeError("boom")

    async def run_loop():
        with (
            patch.object(update_checker.asyncio, "sleep", fake_sleep),
            patch.object(update_checker, "check_for_update", failing_check),
        ):
            with pytest.raises(asyncio.CancelledError):
                await update_checker._check_loop()

    asyncio.run(run_loop())

    assert checks == 2
    assert len(sleeps) == 3


def test_start_update_checker_respects_disable_env(monkeypatch):
    monkeypatch.setenv(update_checker.DISABLE_ENV_VAR, "1")

    async def run():
        start_update_checker()
        assert update_checker._task is None

    asyncio.run(run())


def test_start_update_checker_schedules_a_single_task(monkeypatch):
    monkeypatch.delenv(update_checker.DISABLE_ENV_VAR, raising=False)

    async def run():
        with patch.object(update_checker, "_check_loop", lambda: asyncio.sleep(0)):
            start_update_checker()
            first_task = update_checker._task
            assert first_task is not None

            start_update_checker()
            assert update_checker._task is first_task

            stop_update_checker()
            assert update_checker._task is None

    asyncio.run(run())


def _distribution_with(direct_url):
    """Fake a dist whose direct_url.json is `direct_url` (None = absent)."""

    class FakeDistribution:
        def read_text(self, filename):
            return direct_url

    return FakeDistribution()


@pytest.mark.parametrize(
    "direct_url",
    [
        json.dumps({"url": "file:///src/leaf", "dir_info": {"editable": True}}),
        json.dumps({"url": "file:///src/leaf", "dir_info": {}}),
        json.dumps({"url": "https://gitlab.com/leaf-framework/leaf", "vcs_info": {"vcs": "git"}}),
        json.dumps({"url": "file:///tmp/leaf_framework-1.0-py3-none-any.whl", "archive_info": {}}),
    ],
    ids=["editable", "local-path", "git", "local-wheel"],
)
def test_non_pypi_installs_are_never_pip_upgraded(direct_url):
    """pip writes direct_url.json only for direct references -- none of these came from PyPI."""
    with patch.object(update_checker, "distribution", return_value=_distribution_with(direct_url)):
        assert is_source_install() is True


def test_pypi_install_has_no_direct_url():
    """A plain `pip install leaf-framework` leaves no direct_url.json, so it is upgradable."""
    with patch.object(update_checker, "distribution", return_value=_distribution_with(None)):
        assert is_source_install() is False


def test_missing_metadata_treated_as_source_checkout():
    from importlib.metadata import PackageNotFoundError

    with patch.object(update_checker, "distribution", side_effect=PackageNotFoundError):
        assert is_source_install() is True


def test_fetch_survives_non_httpx_failures():
    """Proxy/SSL misconfiguration raises outside httpx's own hierarchy."""

    class ExplodingClient:
        def __init__(self, error):
            self.error = error

        async def __aenter__(self):
            raise self.error

        async def __aexit__(self, *exc_info):
            return False

    for error in (OSError("SSL_CERT_FILE missing"), ValueError("bad proxy url"), RuntimeError("boom")):

        def make_client(error=error, **kwargs):
            return ExplodingClient(error)

        with patch.object(update_checker.httpx, "AsyncClient", make_client):
            assert asyncio.run(fetch_latest_version()) is None


def test_fetch_propagates_cancellation():
    """Shutdown must still be able to cancel a check in flight."""

    class CancellingClient:
        async def __aenter__(self):
            raise asyncio.CancelledError

        async def __aexit__(self, *exc_info):
            return False

    async def run():
        with patch.object(update_checker.httpx, "AsyncClient", lambda **kwargs: CancellingClient()):
            with pytest.raises(asyncio.CancelledError):
                await fetch_latest_version()

    asyncio.run(run())


def test_fetch_handles_unexpected_payload():
    """A 200 response that isn't PyPI's JSON shape must not raise."""

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            if isinstance(self.payload, Exception):
                raise self.payload
            return self.payload

    class Client:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url):
            return Response(self.payload)

    for payload in ({}, {"info": {}}, {"info": None}, [], ValueError("not json")):

        def make_client(payload=payload, **kwargs):
            return Client(payload)

        with patch.object(update_checker.httpx, "AsyncClient", make_client):
            assert asyncio.run(fetch_latest_version()) is None


def test_start_update_checker_never_raises():
    """It runs as a NiceGUI startup handler -- it must not be able to block startup."""

    def exploding_create_task(coro, *args, **kwargs):
        coro.close()  # keep pytest from warning about a coroutine never awaited
        raise RuntimeError("no running event loop")

    async def run():
        with patch.object(update_checker.asyncio, "create_task", exploding_create_task):
            start_update_checker()  # must not raise
        assert update_checker._task is None

    asyncio.run(run())


def test_stop_update_checker_never_raises():
    class BadTask:
        def cancel(self):
            raise RuntimeError("cannot cancel")

    update_checker._task = BadTask()
    stop_update_checker()  # must not raise


def test_source_check_defaults_to_source_on_unreadable_metadata():
    """An unreadable metadata dir must not offer to pip over the user's install."""
    with patch.object(update_checker, "distribution", side_effect=OSError("permission denied")):
        assert is_source_install() is True


def test_source_check_handles_malformed_direct_url():
    """The file's presence is what matters, so unparseable content is still 'not from PyPI'."""
    with patch.object(update_checker, "distribution", return_value=_distribution_with("{not json")):
        assert is_source_install() is True


def test_failed_check_is_flagged_so_the_ui_can_tell_it_apart():
    """A failed check must not read as 'unchanged, so up to date'."""

    async def good_fetch():
        return "0.7.0"

    async def bad_fetch():
        return None

    with (
        patch.object(update_checker, "__version__", "0.7.0"),
        patch.object(update_checker, "fetch_latest_version", side_effect=good_fetch),
    ):
        status = asyncio.run(check_for_update())
    assert status.last_check_failed is False
    assert status.latest_version == "0.7.0"

    # PyPI goes away: the previous result stays put, but the flag says why
    with patch.object(update_checker, "fetch_latest_version", side_effect=bad_fetch):
        status = asyncio.run(check_for_update())
    assert status.last_check_failed is True
    assert status.latest_version == "0.7.0"

    # ...and a later success clears it again
    with (
        patch.object(update_checker, "__version__", "0.7.0"),
        patch.object(update_checker, "fetch_latest_version", side_effect=good_fetch),
    ):
        status = asyncio.run(check_for_update())
    assert status.last_check_failed is False


def test_manual_check_does_not_need_the_scheduled_one():
    """check_for_update() is callable on its own, which is what the version label does."""

    async def fake_fetch():
        return "1.2.3"

    with (
        patch.object(update_checker, "__version__", "1.0.0"),
        patch.object(update_checker, "fetch_latest_version", side_effect=fake_fetch),
    ):
        status = asyncio.run(check_for_update())

    assert status.update_available is True
    assert update_checker._task is None  # no background loop was involved
