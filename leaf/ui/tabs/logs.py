"""LEAF Logs tab."""

import logging

from nicegui import ui

from leaf.ui.constants import MAX_LOG_LINES
from leaf.ui.utils import LogElementHandler
from leaf.utility.logger.logger_utils import clear_log_buffer, get_log_buffer, get_logger

logger = get_logger(__name__, log_file="input_module.log")

# Log level options
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def create_logs_tab(logs_tab: ui.tab) -> None:
    """
    Create the logs tab panel.

    Args:
        logs_tab: The tab component this panel belongs to
    """
    with ui.tab_panel(logs_tab).classes("w-full p-6"):
        with ui.card().classes("leaf-card w-full"):
            with ui.card_section().classes("w-full"):
                with ui.row().classes("items-center justify-between mb-4"):
                    with ui.row().classes("items-center"):
                        ui.icon("article", size="2rem").classes("text-icon")
                        ui.label("LEAF System Logs").classes("text-2xl font-bold text-heading ml-2")
                    with ui.row().classes("items-center gap-2"):
                        ui.html('<span class="status-indicator status-online"></span>', sanitize=False)
                        ui.label("Live Logging").classes("text-sm font-semibold text-body")

                # Store current log level and handler reference
                current_level = {"value": logging.INFO}
                handler_ref = {"handler": None}

                # Log controls
                with ui.row().classes("items-center gap-4 mb-4"):

                    def clear_logs():
                        log.clear()
                        clear_log_buffer()
                        ui.notify("Logs cleared", icon="clear_all", color="info")
                        logger.info("Log display cleared by user")

                    def download_logs():
                        # This would be implemented to download actual log files
                        ui.notify("Log download feature coming soon", icon="download", color="info")

                    def on_level_change(e):
                        new_level = LOG_LEVELS[e.value]
                        current_level["value"] = new_level

                        # Update handler level for new incoming logs
                        if handler_ref["handler"]:
                            handler_ref["handler"].setLevel(new_level)

                        # Re-filter and display existing logs
                        log.clear()
                        log_buffer = list(get_log_buffer())
                        for log_msg in log_buffer:
                            # Parse log level from message (format: "timestamp - name - LEVEL - message")
                            try:
                                parts = log_msg.split(" - ")
                                if len(parts) >= 3:
                                    msg_level = parts[2].strip()
                                    if msg_level in LOG_LEVELS and LOG_LEVELS[msg_level] >= new_level:
                                        log.push(log_msg)
                            except Exception:
                                # If parsing fails, show the message anyway
                                log.push(log_msg)

                        ui.notify(f"Log level set to {e.value}", icon="filter_list", color="info")

                    ui.select(
                        list(LOG_LEVELS.keys()),
                        value="INFO",
                        label="Log Level",
                        on_change=on_level_change,
                    ).classes("w-32")

                    ui.button("Clear", icon="clear_all", on_click=clear_logs).classes(
                        "btn-tertiary px-4 py-2 rounded transition-colors"
                    )
                    ui.button("Download", icon="download", on_click=download_logs).classes(
                        "btn-secondary px-4 py-2 rounded transition-colors"
                    )

                # Enhanced log display with better styling - constrain width and enable scrolling
                log = (
                    ui.log(max_lines=MAX_LOG_LINES)
                    .classes(
                        "w-full h-96 bg-log-display text-green-400 font-mono text-sm p-4 rounded-lg border overflow-auto"
                    )
                    .style(
                        "box-sizing: border-box; width: 100%; max-width: 100%; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word;"
                    )
                )

                # Replay existing logs from shared buffer (includes all logs from startup)
                # Filter by current level (default INFO)
                log_buffer = list(get_log_buffer())
                for log_msg in log_buffer:
                    try:
                        parts = log_msg.split(" - ")
                        if len(parts) >= 3:
                            msg_level = parts[2].strip()
                            if msg_level in LOG_LEVELS and LOG_LEVELS[msg_level] >= current_level["value"]:
                                log.push(log_msg)
                    except Exception:
                        log.push(log_msg)

                # Set up handler for this client to receive live updates
                try:
                    handler = LogElementHandler(log)
                    handler.setLevel(current_level["value"])  # Set initial level to INFO
                    handler_ref["handler"] = handler
                    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                    handler.setFormatter(formatter)

                    # Attach to root logger to capture ALL logs for this client
                    root_logger = logging.getLogger()
                    root_logger.addHandler(handler)

                    # Clean up handler when client disconnects
                    def cleanup_handler():
                        try:
                            root_logger.removeHandler(handler)
                            logger.debug("Log handler removed for disconnected client")
                        except Exception as e:
                            logger.debug(f"Error removing log handler: {e}")

                    ui.context.client.on_disconnect(cleanup_handler)
                    logger.debug("Logger interface connected and ready!")
                except Exception as e:
                    logger.error(f"Failed to set up log handler: {e}", exc_info=True)
                    ui.notify("Error setting up live logging", color="warning")
