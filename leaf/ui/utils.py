"""Utility functions and classes for LEAF UI."""

import asyncio
import logging
import os
import subprocess
import sys
from typing import Any

from nicegui import ui

from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


class LogElementHandler(logging.Handler):
    """A logging handler that emits messages to a log element."""

    def __init__(self, element: ui.log, level: int = logging.NOTSET) -> None:
        self.element = element
        self._emitting = False  # Recursion guard
        super().__init__(level)

    def emit(self, record: logging.LogRecord) -> None:
        # Prevent recursion when NiceGUI logs warnings about deleted clients
        if self._emitting:
            return

        try:
            self._emitting = True
            msg = self.format(record)
            self.element.push(msg)
        except Exception:
            # Silently ignore errors to prevent recursion
            # Don't call handleError() as it triggers logging which creates infinite loop
            pass
        finally:
            self._emitting = False


def _run_pip(*args: str) -> subprocess.CompletedProcess[str]:
    """
    Run pip in the interpreter currently running LEAF.

    Blocking; call it off the event loop (asyncio.to_thread) so the UI keeps
    responding while pip works.

    Args:
        *args: Arguments passed to pip, e.g. "install", "--upgrade", "git+<url>"

    Returns:
        The completed pip process, for the caller to check returncode/stderr
    """
    return subprocess.run(
        [sys.executable, "-m", "pip", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


# Set (1/true/yes) where the adapters are fixed, e.g. a shared deployment whose adapters come from its image
ADAPTER_INSTALL_DISABLE_ENV = "LEAF_DISABLE_ADAPTER_INSTALL"


def adapter_install_disabled() -> bool:
    """True when installing and uninstalling adapters from the web interface is switched off."""
    return os.environ.get(ADAPTER_INSTALL_DISABLE_ENV, "").strip().lower() in ("1", "true", "yes")


def _refused(action: str) -> bool:
    """Tell the user and return True when adapter installs are switched off, so pip never runs."""
    if not adapter_install_disabled():
        return False
    logger.warning(f"{action} adapters is disabled via {ADAPTER_INSTALL_DISABLE_ENV}")
    ui.notify(f"{action} adapters is disabled on this LEAF", type="warning", position="top", timeout=5000)
    return True


async def install_adapter(adapter: dict[Any, Any]) -> None:
    """
    Install a LEAF adapter from a Git repository.

    Args:
        adapter: Dictionary containing adapter metadata including 'repo_url' and 'name'
    """
    if _refused("Installing"):
        return
    adapter_name = adapter.get("name") or adapter.get("adapter_id", "adapter")
    logger.info(f"Installing {adapter_name}...")
    repository = adapter["repo_url"]

    # Show "installing" notification
    ui.notify(f"Installing {adapter_name}... This may take a moment.", type="info", position="top", timeout=3000)

    # --force-reinstall so a re-install always re-clones and re-checks the
    # repo's default branch HEAD -- these adapters' pyproject.toml versions
    # don't get bumped per commit, so a plain `pip install` would see the
    # already-installed version as satisfying the requirement and skip
    # fetching the newer commit entirely. --no-deps keeps the force away from
    # the dependency tree (which may include LEAF itself); the second, plain
    # install then only adds dependencies that are still missing.
    try:
        result = await asyncio.to_thread(
            _run_pip, "install", "--upgrade", "--force-reinstall", "--no-deps", f"git+{repository}"
        )
        if result.returncode == 0:
            result = await asyncio.to_thread(_run_pip, "install", f"git+{repository}")
    except Exception as e:
        logger.error(f"Could not run pip to install {adapter_name}: {e}", exc_info=True)
        ui.notify(
            f"Could not start the installation of {adapter_name}",
            type="negative",
            position="top",
            close_button=True,
            timeout=8000,
        )
        return

    if result.returncode != 0:
        logger.error(f"Failed to install {adapter_name}: {result.stderr}")
        ui.notify(f"Failed to install {adapter_name}", type="negative", position="top", close_button=True, timeout=8000)
        return

    logger.info(f"Installed {adapter_name}:\n{result.stdout}")
    ui.notify(
        f"Successfully installed {adapter_name}! Click the Refresh button to detect it.",
        type="positive",
        position="top",
        close_button=True,
        timeout=10000,
    )


async def uninstall_adapter(installed_adapter: dict[Any, Any]) -> None:
    """
    Uninstall a LEAF adapter package.

    Args:
        installed_adapter: Dictionary containing adapter metadata with 'name' field
    """
    if _refused("Uninstalling"):
        return
    package_name = installed_adapter.get("name")

    if not package_name:
        logger.error(f"Cannot uninstall adapter without package name: {installed_adapter}")
        ui.notify(
            "Cannot uninstall adapter without package name",
            type="negative",
            position="top",
            close_button=True,
            timeout=8000,
        )
        return

    logger.info(f"Uninstalling {package_name}...")
    ui.notify(f"Uninstalling {package_name}... This may take a moment.", type="info", position="top", timeout=3000)

    try:
        result = await asyncio.to_thread(_run_pip, "uninstall", "-y", package_name)
    except Exception as e:
        logger.error(f"Could not run pip to uninstall {package_name}: {e}", exc_info=True)
        ui.notify(
            f"Could not start the removal of {package_name}",
            type="negative",
            position="top",
            close_button=True,
            timeout=8000,
        )
        return

    if result.returncode != 0:
        logger.error(f"Failed to uninstall {package_name}: {result.stderr}")
        ui.notify(
            f"Failed to uninstall {package_name}", type="negative", position="top", close_button=True, timeout=8000
        )
        return

    logger.info(f"Uninstalled {package_name} successfully.")
    ui.notify(
        f"Successfully uninstalled {package_name}! Click the Refresh button to update the list.",
        type="positive",
        position="top",
        close_button=True,
        timeout=10000,
    )
