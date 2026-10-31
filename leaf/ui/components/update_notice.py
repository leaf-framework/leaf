"""Header indicator offering the update found by leaf.ui.update_checker."""

import asyncio

from nicegui import ui

from leaf import __version__
from leaf.ui.components.app_control import restart_leaf
from leaf.ui.update_checker import (
    PYPI_PROJECT_URL,
    UNKNOWN_VERSION,
    check_for_update,
    get_update_status,
    install_update,
    is_source_install,
)
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="interface.log")

# How often each open page re-reads the (in-memory) update status. The check
# itself runs at most weekly in the background; this only decides how quickly
# an already-open tab notices its result.
POLL_INTERVAL_SECONDS = 60.0


async def _perform_update(dialog: ui.dialog, update_button: ui.button, latest_version: str | None) -> None:
    """
    Run pip in a worker thread, then re-exec LEAF on success.

    Args:
        dialog: The confirmation dialog to update in place
        update_button: The dialog's confirm button, disabled while pip runs
        latest_version: Version to install, or None for the latest available
    """
    update_button.disable()
    ui.notify("Updating LEAF... this may take a moment.", type="info", position="top", timeout=5000)

    try:
        result = await asyncio.to_thread(install_update, latest_version)
    except Exception as e:
        # pip could not even be started (no interpreter, no permission to
        # spawn). Re-enable the button so the user can retry rather than
        # leaving them with a dead dialog.
        update_button.enable()
        logger.error(f"Could not run pip to update LEAF: {e}", exc_info=True)
        ui.notify(
            "Could not start the update - see the Logs tab for details.",
            type="negative",
            position="top",
            close_button=True,
            timeout=8000,
        )
        return

    if result.returncode != 0:
        update_button.enable()
        logger.error(f"Failed to update LEAF: {result.stderr}")
        ui.notify(
            "Update failed - LEAF is unchanged. See the Logs tab for details.",
            type="negative",
            position="top",
            close_button=True,
            timeout=8000,
        )
        return

    logger.info(f"LEAF updated successfully:\n{result.stdout}")
    dialog.close()
    ui.notify(
        "Update installed. Restarting LEAF - reload this page in a few seconds.",
        type="positive",
        position="top",
        timeout=10000,
    )
    # Let the notification render before the process is replaced
    _ = ui.timer(1.5, restart_leaf, once=True)


def _open_update_dialog() -> None:
    """Show what is available and, for a normal install, offer to install it."""
    status = get_update_status()
    latest_version = status.latest_version

    with ui.dialog() as dialog, ui.card().classes("w-96"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("system_update", size="1.5rem").classes("text-icon")
            ui.label("LEAF update available").classes("text-xl font-bold text-heading")

        ui.label(f"Installed: v{__version__}").classes("text-sm text-body")
        ui.label(f"Available: v{latest_version}").classes("text-sm text-body font-bold")
        ui.link("View release on PyPI", PYPI_PROJECT_URL, new_tab=True).classes("text-sm")

        if is_source_install():
            # Installing a PyPI wheel over a checkout or a git install would
            # silently replace what the user actually deployed.
            ui.label(
                "LEAF was not installed from PyPI, so it will not be updated from here. "
                "Update it the way you installed it - git pull in your checkout, or "
                "pip install --upgrade git+<repository>."
            ).classes("text-sm text-body mt-2")
            with ui.row().classes("w-full justify-end mt-2"):
                ui.button("Close", on_click=dialog.close).classes("btn-tertiary")
        else:
            ui.label("LEAF will restart once the update is installed.").classes("text-sm text-body mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("Not now", on_click=dialog.close).classes("btn-tertiary")
                update_button = ui.button("Update & Restart", icon="download").classes("btn-primary")
                update_button.on_click(lambda: _perform_update(dialog, update_button, latest_version))

    dialog.open()


def create_update_notice() -> None:
    """
    Add the version label and the "update available" button to the header.

    The badge starts hidden and stays hidden until a check finds a newer
    release. Clicking the version label runs a check immediately, for anyone
    who does not want to wait for the scheduled one.
    """
    version_label = (
        ui.label(f"v{__version__}")
        .classes("text-xs opacity-70 ml-2 self-end mb-1 cursor-pointer hover:opacity-100")
        .tooltip("Click to check for updates")
    )

    notice_button = (
        ui.button("", icon="system_update", on_click=_open_update_dialog)
        .props('flat dense title="A newer LEAF version is available"')
        .classes("text-yellow-300 text-xs ml-2 self-end mb-1")
    )
    notice_button.visible = False

    def refresh_notice() -> None:
        # The timer outlives its page when a browser tab goes away; touching a
        # deleted element would raise on every tick from then on.
        if notice_button.is_deleted:
            return

        status = get_update_status()
        if notice_button.visible == status.update_available:
            return
        if status.update_available:
            notice_button.text = f"v{status.latest_version} available"
        notice_button.visible = status.update_available

    checking = False

    async def check_now() -> None:
        """Run a check right now and report the outcome, whatever it is."""
        nonlocal checking
        if checking:
            return

        checking = True
        version_label.text = "checking..."
        try:
            status = await check_for_update()
        finally:
            checking = False
            version_label.text = f"v{__version__}"

        refresh_notice()

        # Colour carries the answer at a glance: green only when this install
        # is genuinely current, red when the check could not be made, amber
        # for anything the user may want to act on.
        if status.last_check_failed:
            ui.notify(
                "Could not reach PyPI to check for updates.",
                type="negative",
                position="top",
                close_button=True,
                timeout=6000,
            )
        elif status.update_available:
            ui.notify(
                f"LEAF v{status.latest_version} is available - you are on v{__version__}.",
                type="warning",
                position="top",
                close_button=True,
                timeout=6000,
            )
        elif __version__ == UNKNOWN_VERSION:
            # No package metadata, so there is nothing meaningful to compare
            # against -- say so rather than claiming this install is current.
            ui.notify(
                f"Latest release on PyPI is v{status.latest_version}. This install reports no version, "
                "so LEAF cannot tell whether it is newer.",
                type="warning",
                position="top",
                close_button=True,
                timeout=8000,
            )
        else:
            ui.notify(f"LEAF is up to date (v{__version__}).", type="positive", position="top", timeout=4000)

    version_label.on("click", check_now)

    refresh_notice()
    ui.timer(POLL_INTERVAL_SECONDS, refresh_notice)
