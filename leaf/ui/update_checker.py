"""Background check for a newer LEAF release on PyPI.

Deliberately *not* run at startup: a fresh install or a restart-after-config-
change is exactly when the user is least interested in being nagged, and a
network call there would delay the UI's first paint. Instead the first check
happens FIRST_CHECK_DELAY_SECONDS into a session and repeats weekly after
that, so a machine that gets restarted often re-arms the one-hour delay each
time rather than hitting PyPI on every launch.

The schedule is intentionally in-memory only -- no "last checked" file. A
restart starting the hour over is the behaviour we want, not a bug to work
around with persistence.
"""

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution

import httpx

from leaf import __version__
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="interface.log")

PACKAGE_NAME = "leaf-framework"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
PYPI_PROJECT_URL = f"https://pypi.org/project/{PACKAGE_NAME}/"

FIRST_CHECK_DELAY_SECONDS = 60 * 60  # one hour into a session
RECHECK_INTERVAL_SECONDS = 7 * 24 * 60 * 60  # weekly from then on
REQUEST_TIMEOUT_SECONDS = 10.0

# Set to 1/true/yes to switch the check off entirely (air-gapped installs,
# site policies that forbid outbound calls from lab machines).
DISABLE_ENV_VAR = "LEAF_DISABLE_UPDATE_CHECK"

# leaf/__init__.py falls back to this when the package metadata is missing,
# i.e. LEAF is being run straight from a source tree. Every release would
# compare as "newer" than it, so treat it as "version unknown" instead.
UNKNOWN_VERSION = "0.0.0"


@dataclass
class UpdateStatus:
    """Result of the most recent PyPI check (all None/False until one runs)."""

    latest_version: str | None = None
    update_available: bool = False
    last_checked: float | None = None
    last_check_failed: bool = False


_status = UpdateStatus()
_task: asyncio.Task | None = None


def get_update_status() -> UpdateStatus:
    """Return the current update status. Never blocks, never hits the network."""
    return _status


def parse_version(value: str) -> tuple[int, ...] | None:
    """
    Parse a plain numeric version into a comparable tuple.

    LEAF releases are plain MAJOR.MINOR.PATCH (CI publishes vMAJOR.MINOR
    padded to MAJOR.MINOR.0), so anything carrying a pre/post/dev suffix is
    deliberately reported as unparseable rather than guessed at -- guessing
    wrong would nag the user about a "newer" version forever.

    Args:
        value: Version string to parse

    Returns:
        Tuple of version components, or None if not purely numeric
    """
    parts = value.strip().split(".")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))

    if not numbers:
        return None
    return tuple(numbers)


def is_newer(candidate: str, installed: str) -> bool:
    """
    Return True if `candidate` is a strictly newer release than `installed`.

    Anything ambiguous -- an unparseable version on either side, or the
    0.0.0 "running from source" fallback -- returns False, so an uncertain
    comparison never produces an update prompt.

    Args:
        candidate: Version offered by PyPI
        installed: Version currently running

    Returns:
        True if the user should be offered an update
    """
    if installed == UNKNOWN_VERSION:
        return False

    candidate_parts = parse_version(candidate)
    installed_parts = parse_version(installed)
    if candidate_parts is None or installed_parts is None:
        return False

    # Pad both to the same length so 1.4 and 1.4.0 compare equal
    length = max(len(candidate_parts), len(installed_parts))
    candidate_parts += (0,) * (length - len(candidate_parts))
    installed_parts += (0,) * (length - len(installed_parts))
    return candidate_parts > installed_parts


async def fetch_latest_version() -> str | None:
    """
    Ask PyPI for the latest published LEAF version.

    Returns:
        The version string, or None if PyPI was unreachable or replied with
        something unexpected (logged as a warning, never surfaced to the user)
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(PYPI_JSON_URL)
            response.raise_for_status()
            return str(response.json()["info"]["version"])
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Deliberately broad. Beyond httpx's own errors (no DNS, no route,
        # timeout, 5xx) this call can fail on things well outside its
        # hierarchy: a broken proxy env var, an SSL_CERT_FILE pointing at a
        # missing bundle, a JSON body that is not what PyPI usually returns.
        # None of that is worth more than a log line -- "could not find out"
        # is a perfectly good answer here.
        logger.warning(f"Could not check PyPI for a newer {PACKAGE_NAME}: {type(e).__name__}: {e}")
        return None


async def check_for_update() -> UpdateStatus:
    """
    Run a single check and update the module-level status.

    Returns:
        The (possibly unchanged) update status
    """
    latest = await fetch_latest_version()
    if latest is None:
        _status.last_check_failed = True
        return _status

    _status.last_check_failed = False
    _status.latest_version = latest
    _status.update_available = is_newer(latest, __version__)
    _status.last_checked = time.time()

    if _status.update_available:
        logger.info(f"LEAF update available: v{__version__} installed, v{latest} on PyPI")
    else:
        logger.debug(f"LEAF is up to date (v{__version__}, latest on PyPI is v{latest})")
    return _status


async def _check_loop() -> None:
    """Sleep an hour, check, then check once a week for as long as LEAF runs."""
    delay = FIRST_CHECK_DELAY_SECONDS
    while True:
        try:
            await asyncio.sleep(delay)
            await check_for_update()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # A single failure must never kill the loop -- same resilience the
            # polling watchers needed (see commit 4c46d03).
            logger.error(f"Update check failed unexpectedly: {e}", exc_info=True)
        delay = RECHECK_INTERVAL_SECONDS


def start_update_checker() -> None:
    """
    Start the background check. Safe to call more than once; needs a running event loop.

    Runs as a NiceGUI startup handler, so it swallows its own failures: an
    optional convenience must never stop the web interface from coming up.
    """
    global _task

    try:
        if os.environ.get(DISABLE_ENV_VAR, "").strip().lower() in ("1", "true", "yes"):
            logger.info(f"Update check disabled via {DISABLE_ENV_VAR}")
            return

        if _task is not None and not _task.done():
            return

        _task = asyncio.create_task(_check_loop())
        logger.info(
            f"Update check scheduled in {FIRST_CHECK_DELAY_SECONDS // 60} minutes, "
            f"then every {RECHECK_INTERVAL_SECONDS // 86400} days"
        )
    except Exception as e:
        logger.warning(f"Could not start the update check, continuing without it: {e}")


def stop_update_checker() -> None:
    """Cancel the background check (called on shutdown)."""
    global _task
    try:
        if _task is not None:
            _task.cancel()
            _task = None
    except Exception as e:
        logger.warning(f"Could not cancel the update check: {e}")


def is_source_install() -> bool:
    """
    Return True when LEAF was installed from anything other than PyPI.

    Upgrading such an install from PyPI would quietly swap what the user
    actually deployed -- an editable checkout, a `pip install git+...`, a
    local wheel -- for a released wheel, so the UI shows the new version as
    information only in those cases instead of offering to install it.

    The test is PEP 610's direct_url.json, which pip writes only for direct
    references (VCS, local path, editable). A plain `pip install
    leaf-framework` from an index leaves no such file, so "the file exists"
    means "this did not come from PyPI".
    """
    try:
        direct_url = distribution(PACKAGE_NAME).read_text("direct_url.json")
    except PackageNotFoundError:
        # No installed metadata at all: running straight from the source tree
        return True
    except Exception as e:
        # Unreadable metadata -- assume a source install, the answer that
        # cannot damage anything (it only ever declines to run pip).
        logger.warning(f"Could not determine how {PACKAGE_NAME} was installed: {e}")
        return True

    return bool(direct_url)


def install_update(version: str | None = None) -> subprocess.CompletedProcess:
    """
    Upgrade LEAF with pip, into the interpreter that is currently running it.

    Blocking; call it off the event loop (asyncio.to_thread) so the UI keeps
    responding while pip works.

    Args:
        version: Exact version to install, or None for the latest available

    Returns:
        The completed pip process, for the caller to check returncode/stderr
    """
    requirement = PACKAGE_NAME if version is None else f"{PACKAGE_NAME}=={version}"
    logger.info(f"Installing {requirement}...")
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", requirement],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
