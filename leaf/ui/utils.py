"""Utility functions and classes for LEAF UI."""

import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict

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


def install_adapter(adapter: dict[Any, Any]) -> None:
    """
    Install a LEAF adapter from a Git repository.

    Args:
        adapter: Dictionary containing adapter metadata including 'repo_url' and 'name'
    """
    adapter_name = adapter.get('name') or adapter.get('adapter_id', 'adapter')
    logger.info(f"Installing {adapter_name}...")
    repository = adapter['repo_url']

    # Show "installing" notification
    ui.notify(
        f"Installing {adapter_name}... This may take a moment.",
        type='info',
        position='top',
        timeout=3000
    )

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", f'git+{repository}'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        logger.error(f"Failed to install {adapter_name}: {result.stderr}")
        ui.notify(
            f"Failed to install {adapter_name}",
            type='negative',
            position='top',
            close_button=True,
            timeout=8000
        )
        return

    logger.info(f"Installed {adapter_name}:\n{result.stdout}")
    ui.notify(
        f"Successfully installed {adapter_name}! Click the Refresh button to detect it.",
        type='positive',
        position='top',
        close_button=True,
        timeout=10000
    )


def uninstall_adapter(installed_adapter: Dict) -> None:
    """
    Uninstall a LEAF adapter package.

    Args:
        installed_adapter: Dictionary containing adapter metadata with 'name' field
    """
    print(f"Uninstalling {installed_adapter}...")
    package_name = installed_adapter.get('name')

    if not package_name:
        print(f"Cannot uninstall adapter without package name: {installed_adapter}")
        ui.notify(
            "Cannot uninstall adapter without package name",
            type='negative',
            position='top',
            close_button=True,
            timeout=8000
        )
        return

    logger.info(f"Uninstalling {package_name}...")
    ui.notify(
        f"Uninstalling {package_name}... This may take a moment.",
        type='info',
        position='top',
        timeout=3000
    )

    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", package_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode == 0:
        print(f"Uninstalled {package_name} successfully.")
        logger.info(f"Uninstalled {package_name} successfully.")
        ui.notify(
            f"Successfully uninstalled {package_name}! Click the Refresh button to update the list.",
            type='positive',
            position='top',
            close_button=True,
            timeout=10000
        )
    else:
        print(f"Failed to uninstall {package_name}.\nError: {result.stderr}")
        logger.error(f"Failed to uninstall {package_name}: {result.stderr}")
        ui.notify(
            f"Failed to uninstall {package_name}",
            type='negative',
            position='top',
            close_button=True,
            timeout=8000
        )
