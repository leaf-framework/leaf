"""Header status dot: red when a connection is down, amber when one is insecure, green otherwise."""

from collections.abc import Callable

from nicegui import ui

from leaf.adapters.equipment_adapter import EquipmentAdapter
from leaf.utility.running_adapters import adapters

# Adapters can start, restart or lose their connection after the page loads, so the dot re-checks.
POLL_INTERVAL_SECONDS = 5.0


def _by_instance(check: Callable[[EquipmentAdapter], list[str]]) -> dict[str, list[str]]:
    """Each finding with the instances it affects; the shared output reports the same one for every instance."""
    found: dict[str, list[str]] = {}
    for adapter in list(adapters):
        instance = adapter.metadata_manager.get_instance_id()
        for finding in check(adapter):
            found.setdefault(finding, [])
            if instance not in found[finding]:
                found[finding].append(instance)
    return found


def collect_security_warnings() -> dict[str, list[str]]:
    return _by_instance(lambda adapter: adapter.security_warnings())


def collect_disconnected() -> dict[str, list[str]]:
    return _by_instance(lambda adapter: adapter.disconnected())


def _findings_table(findings: dict[str, list[str]], label: str) -> None:
    ui.table(
        columns=[
            {"name": "finding", "label": label, "field": "finding", "align": "left"},
            {"name": "instances", "label": "Instances", "field": "instances", "align": "left"},
        ],
        rows=[{"finding": finding, "instances": ", ".join(names)} for finding, names in findings.items()],
    ).props("flat dense wrap-cells").classes("w-full")


@ui.refreshable
def _status_body() -> None:
    down = collect_disconnected()
    issues = collect_security_warnings()
    ui.label(f"{len(adapters)} instance(s) running").classes("text-sm text-body")

    with ui.row().classes("items-center gap-2 mt-2"):
        if down:
            ui.icon("link_off", size="1.5rem").classes("text-red-500")
        else:
            ui.icon("link", size="1.5rem").classes("text-green-500")
        ui.label("Connections").classes("text-lg font-bold text-heading")
    if down:
        ui.label("Not connected right now; LEAF keeps retrying. See the Logs tab for the cause.").classes(
            "text-sm text-body"
        )
        _findings_table(down, "Not connected")
    else:
        ui.label("All inputs and outputs are connected.").classes("text-sm text-body")

    with ui.row().classes("items-center gap-2 mt-2"):
        if issues:
            ui.icon("gpp_maybe", size="1.5rem").classes("text-amber-500")
        else:
            ui.icon("verified_user", size="1.5rem").classes("text-green-500")
        ui.label("Security").classes("text-lg font-bold text-heading")
    if issues:
        ui.label(
            "These connections work, but without credentials or encryption anyone on the network "
            "can read or send data. Fix them in the Configuration tab."
        ).classes("text-sm text-body")
        _findings_table(issues, "Issue")
    else:
        ui.label(
            "No insecure connections to other machines. Connections to this machine "
            "(localhost or a unix socket) are not checked, as their traffic never leaves it."
        ).classes("text-sm text-body")


def _open_status_dialog() -> None:
    with ui.dialog() as dialog, ui.card().classes("min-w-96 max-w-full"):
        ui.label("LEAF status").classes("text-xl font-bold text-heading")
        _status_body()
        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Close", on_click=dialog.close).classes("btn-tertiary")
        # Lives inside the dialog, so it stops when the dialog is deleted on close.
        _ = ui.timer(POLL_INTERVAL_SECONDS, _status_body.refresh)
    _ = dialog.on("hide", dialog.delete)
    dialog.open()


def create_security_status() -> None:
    """Add the clickable status dot and label to the header."""
    with ui.row().classes("items-center mr-4 cursor-pointer").on("click", _open_status_dialog) as row:
        dot = ui.html('<span class="status-indicator status-online"></span>', sanitize=False)
        label = ui.label("System Online").classes("text-sm opacity-90")
    row.tooltip("Click for connection and security status")

    def refresh() -> None:
        # The timer outlives its page when a browser tab goes away.
        if label.is_deleted:
            return
        down = len(collect_disconnected())
        insecure = len(collect_security_warnings())
        if down:
            status, text = "status-offline", f"{down} disconnected"
        elif insecure:
            status, text = "status-warning", f"Online · {insecure} insecure"
        else:
            status, text = "status-online", "System Online"
        dot.content = f'<span class="status-indicator {status}"></span>'
        label.text = text

    refresh()
    _ = ui.timer(POLL_INTERVAL_SECONDS, refresh)
