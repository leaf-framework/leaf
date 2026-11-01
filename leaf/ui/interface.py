"""LEAF NiceGUI web interface."""

import base64
import os
from pathlib import Path

from nicegui import app, ui

from leaf import __version__
from leaf.registry.discovery import discover_adapter_ui_extensions
from leaf.ui.auth import require_password
from leaf.ui.components.header import create_header
from leaf.ui.constants import DEFAULT_PORT, TAB_CLASSES
from leaf.ui.tabs.adapters import create_adapters_tab
from leaf.ui.tabs.configuration import create_configuration_tab
from leaf.ui.tabs.control import create_control_tab
from leaf.ui.tabs.documentation import create_documentation_tab
from leaf.ui.tabs.logs import create_logs_tab
from leaf.ui.tabs.monitoring import create_monitoring_tab
from leaf.ui.update_checker import start_update_checker, stop_update_checker
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="interface.log")

# Global startup error storage
_startup_error: str | None = None


def set_startup_error(error: str) -> None:
    """Set a startup error to be displayed in the UI."""
    global _startup_error
    _startup_error = error
    logger.error(f"Startup error set: {error}")


def get_startup_error() -> str | None:
    """Get the current startup error, if any."""
    return _startup_error


def start_nicegui(port: int = DEFAULT_PORT, config_path: Path | None = None, auto_open_browser: bool = True) -> None:
    """
    Start the LEAF NiceGUI web interface.

    Creates a web-based interface for managing LEAF system configuration,
    viewing logs, managing adapters, and accessing documentation.

    Args:
        port: Port number to run the web server on (default: 8080)
        config_path: Path to the configuration file (if None, will auto-detect)
        auto_open_browser: Whether to automatically open browser (default: True)
    """
    # Load markdown content and CSS from files
    curr_dir = Path(os.path.dirname(os.path.realpath(__file__)))
    markdown_dir = curr_dir / "markdown"

    with open(markdown_dir / "configuration_help.md") as f:
        _config_help_md = f.read()  # noqa: F841

    with open(markdown_dir / "documentation_main.md") as f:
        docs_main_md = f.read()

    with open(markdown_dir / "documentation_protips.md") as f:
        docs_protips_md = f.read()

    with open(curr_dir / "styles.css") as f:
        custom_css = f.read()

    with open(curr_dir / "scripts.js") as f:
        custom_js = f.read()

    # Load the actual LEAF icon from images/icon.svg
    svg_path: Path = curr_dir / "images" / "icon.svg"
    favicon_b64 = "PHN2ZyB3aWR0aD0iMzIiIGhlaWdodD0iMzIiIHZpZXdCb3g9IjAgMCAzMiAzMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTggMTZDOCAxNiAxNiA8IDE2IDhDMTYgOCAyNCAxNiAyNCAxNkMyNCAxNiAxNiAyNCAxNiAyNEMxNiAyNCA4IDE2IDggMTZaIiBmaWxsPSIjNDA5NkZGIiBzdHJva2U9IiMyNTYzRUIiIHN0cm9rZS13aWR0aD0iMiIvPgo8L3N2Zz4K"

    if os.path.exists(svg_path):
        with open(svg_path) as svg_file:
            svg = svg_file.read()
            favicon_b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")

    # Discover adapter UI extensions ONCE at startup, not per client connection
    logger.info("Discovering adapter UI extensions at startup...")
    adapter_ui_extensions = []
    try:
        adapter_ui_extensions = discover_adapter_ui_extensions()
        logger.info(f"Discovered {len(adapter_ui_extensions)} adapter UI extensions")
    except Exception as e:
        logger.error(f"Error discovering adapter UI extensions: {e}", exc_info=True)

    # Define the main page
    @ui.page("/")
    def index():
        import time

        start_time = time.time()

        try:
            logger.debug("UI index page handler called - starting to build page")
            from nicegui import context as ui_context

            # Log client connection
            try:
                client_ip = ui_context.client.ip if ui_context.client else "unknown"
                logger.debug(f"Client connected from {client_ip}")
            except Exception as e:
                logger.debug(f"Client connected (could not get IP: {e})")

            logger.debug(f"[PERF] Client connection logged: {time.time() - start_time:.3f}s")

            # Clean up on disconnect
            def on_disconnect():
                try:
                    logger.debug("Client disconnected")
                except Exception:
                    pass

            try:
                ui_context.client.on_disconnect(on_disconnect)
            except Exception:
                pass

            # Add custom CSS, JS, and LEAF favicon - set title here
            ui.add_head_html(f"""
                <title>LEAF v{__version__} - Lightweight Equipment Adapter Framework</title>
                <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}">
                <style>
                    {custom_css}
                </style>
                <script>
                    {custom_js}
                </script>
            """)

            # Apply portal color theme
            ui.colors(primary="#f15b25", secondary="#6fd3f2")

            # Dark mode toggle
            dark = ui.dark_mode()

            # Create left sidebar with vertical tabs
            drawer = ui.left_drawer(value=True).classes("bg-gray-50 border-r border-gray-200 pt-4")
            with drawer:
                with ui.tabs(value=None).props("vertical").classes("w-full leaf-sidebar-tabs") as tabs:
                    config_tab: ui.tab = ui.tab("Configuration", icon="settings").classes(TAB_CLASSES)
                    logs_tab = ui.tab("Logs", icon="article").classes(TAB_CLASSES)
                    docs_tab = ui.tab("Documentation", icon="help").classes(TAB_CLASSES)
                    monitor_tab = ui.tab("Monitoring", icon="monitor").classes(TAB_CLASSES)
                    control_tab = ui.tab("Control", icon="tune").classes(TAB_CLASSES)
                    adapters_tab = ui.tab("Adapters", icon="extension").classes(TAB_CLASSES)

                    # Dynamically create tabs for adapter UI extensions
                    adapter_tabs = []
                    for ext in adapter_ui_extensions:
                        ui_config = ext["ui_config"]
                        tab = ui.tab(ui_config["tab_name"], icon=ui_config.get("tab_icon", "extension")).classes(
                            TAB_CLASSES
                        )
                        adapter_tabs.append((tab, ext))
                        logger.debug(f"Created tab for adapter: {ext['adapter_code']}")

            # Attach event handler to logs tab to scroll to bottom
            logs_tab.on("click", lambda: ui.run_javascript("scrollLogToBottom()"))

            # Create header with drawer toggle
            logger.debug(f"[PERF] Creating header: {time.time() - start_time:.3f}s")
            create_header(dark, curr_dir, drawer)
            logger.debug(f"[PERF] Header created: {time.time() - start_time:.3f}s")

            # Show startup error banner if there's an error
            startup_error = get_startup_error()
            if startup_error:
                with ui.card().classes("w-full bg-red-100 border-2 border-red-500 mb-4"):
                    with ui.card_section().classes("w-full"):
                        with ui.row().classes("items-center gap-4 w-full"):
                            ui.icon("error", color="red", size="2rem")
                            with ui.column().classes("flex-1"):
                                ui.label("Configuration Error").classes("text-xl font-bold text-red-700")
                                ui.label(startup_error).classes("text-red-600")
                                ui.label(
                                    "LEAF is running in UI-only mode. Please fix the configuration and restart."
                                ).classes("text-sm text-red-500 mt-2")

            logger.debug(f"[PERF] Tabs structure created: {time.time() - start_time:.3f}s")

            with ui.tab_panels(tabs, value=logs_tab).classes("w-full"):
                # Create all built-in tab panels
                logger.debug(f"[PERF] Creating configuration tab: {time.time() - start_time:.3f}s")
                create_configuration_tab(config_tab, config_path)
                logger.debug(f"[PERF] Configuration tab done: {time.time() - start_time:.3f}s")

                logger.debug(f"[PERF] Creating logs tab: {time.time() - start_time:.3f}s")
                create_logs_tab(logs_tab)
                logger.debug(f"[PERF] Logs tab done: {time.time() - start_time:.3f}s")

                logger.debug(f"[PERF] Creating adapters tab: {time.time() - start_time:.3f}s")
                create_adapters_tab(adapters_tab)
                logger.debug(f"[PERF] Adapters tab done: {time.time() - start_time:.3f}s")

                logger.debug(f"[PERF] Creating documentation tab: {time.time() - start_time:.3f}s")
                create_documentation_tab(docs_tab, docs_main_md, docs_protips_md)
                logger.debug(f"[PERF] Documentation tab done: {time.time() - start_time:.3f}s")

                logger.debug(f"[PERF] Creating monitoring tab: {time.time() - start_time:.3f}s")
                create_monitoring_tab(monitor_tab=monitor_tab)
                create_control_tab(control_tab)
                logger.debug(f"[PERF] Monitoring tab done: {time.time() - start_time:.3f}s")

                # Dynamically create panels for adapter UI extensions
                logger.debug(
                    f"[PERF] Creating {len(adapter_tabs)} adapter extension tabs: {time.time() - start_time:.3f}s"
                )

                for tab, ext in adapter_tabs:
                    try:
                        ui_config = ext["ui_config"]
                        create_panel_func = ui_config["create_panel"]
                        create_panel_func(tab)
                        logger.debug(f"Created panel for adapter: {ext['adapter_code']}")
                    except Exception as e:
                        logger.error(f"Error creating UI panel for adapter {ext['adapter_code']}: {e}")
                        # Create a fallback error panel
                        with ui.tab_panel(tab):
                            ui.label(f"Error loading {ext['adapter_name']} UI").classes("text-red-600")
                logger.debug(f"[PERF] Adapter extension tabs done: {time.time() - start_time:.3f}s")

            logger.debug(f"[PERF] LEAF UI page built successfully in {time.time() - start_time:.3f}s")

        except Exception as e:
            logger.error(f"CRITICAL: UI page handler crashed: {e}", exc_info=True)
            # Try to show error to user
            try:
                ui.label(f"Error building LEAF UI: {e}").classes("text-red-600 text-xl p-8")
                ui.label("Check logs for details. Try refreshing the page.").classes("text-body p-4")
            except Exception:
                pass
            raise

    # Check for a newer LEAF release in the background -- an hour into the
    # session, then weekly. Registered on startup so it runs once per process,
    # not once per connected browser tab.
    app.on_startup(start_update_checker)
    app.on_shutdown(stop_update_checker)

    # Off unless LEAF_UI_PASSWORD is set, e.g. when the pod's UI is reachable by others.
    require_password(app)

    logger.info(f"Starting web interface on port {port}...")
    logger.info(f"Access the LEAF UI at http://localhost:{port}")

    try:
        ui.run(
            reload=False,
            port=port,
            show=auto_open_browser,
            title=f"LEAF v{__version__} - Lightweight Equipment Adapter Framework",
            reconnect_timeout=10.0,  # Give clients 10 seconds to reconnect
        )
        logger.info("NiceGUI web interface stopped normally.")
    except KeyboardInterrupt:
        logger.info("NiceGUI web interface stopped by keyboard interrupt.")
        raise
    except OSError as e:
        if "Address already in use" in str(e):
            logger.error(f"Port {port} is already in use. Please use a different port with --port flag.")
        else:
            logger.error(f"NiceGUI web interface failed to start: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"NiceGUI web interface crashed unexpectedly: {e}", exc_info=True)
        raise
