"""Restart and stop LEAF, from the header or the configuration tab."""

import inspect
import os
import sys
from collections.abc import Callable

from nicegui import ui

from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="interface.log")


def restart_leaf() -> None:
    """Re-exec LEAF with the same arguments, so it reloads the configuration file."""
    logger.info("Restarting LEAF...")
    os.execl(sys.executable, sys.executable, *sys.argv)


def stop_leaf() -> None:
    """Replace the page with a stopped message, then shut LEAF down."""
    logger.info("Stopping LEAF system...")
    # Browsers block window.close(), so tell the user to close the tab instead
    _ = ui.run_javascript("""
        document.body.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;background:#1a1a2e;color:#eee;">' +
            '<h1 style="margin-bottom:1rem;">LEAF has stopped</h1>' +
            '<p style="color:#888;">You can now close this tab.</p>' +
        '</div>';
    """)

    def do_shutdown():
        os.execl(sys.executable, sys.executable, sys.argv[0], "--shutdown")

    # Delay shutdown to allow JavaScript to execute
    _ = ui.timer(1.0, do_shutdown, once=True)


def confirm(
    title: str, text: str, action_label: str, icon: str, button_class: str, action: Callable[[], object]
) -> None:
    """Ask before running an action that interrupts an adapter; the action may be async."""
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        with ui.row().classes("items-center gap-2"):
            _ = ui.icon(icon, size="1.5rem").classes("text-icon")
            _ = ui.label(title).classes("text-xl font-bold text-heading")
        _ = ui.label(text).classes("text-sm text-body")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            _ = ui.button("Cancel", on_click=dialog.close).classes("btn-tertiary")

            async def run():
                _ = dialog.close()
                result = action()
                if inspect.isawaitable(result):
                    await result

            _ = ui.button(action_label, icon=icon, on_click=run).classes(button_class)
    _ = dialog.open()


def create_app_controls() -> None:
    """Add Restart and Stop buttons to the header, each behind a confirmation."""
    _ = ui.button(
        "",
        icon="restart_alt",
        on_click=lambda: confirm(
            "Restart LEAF?",
            "All adapters restart with the saved configuration file. Unsaved editor changes are not applied.",
            "Restart",
            "restart_alt",
            "btn-primary",
            restart_leaf,
        ),
    ).props('flat round color=white title="Restart LEAF"')
    _ = ui.button(
        "",
        icon="stop",
        on_click=lambda: confirm(
            "Stop LEAF?",
            "All adapters stop and this page stops responding.",
            "Stop",
            "stop",
            "btn-danger",
            stop_leaf,
        ),
    ).props('flat round color=white title="Stop LEAF"')
