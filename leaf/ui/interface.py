"""LEAF NiceGUI web interface."""

import base64
import os
from pathlib import Path
from typing import Optional

from nicegui import ui

from leaf.registry.discovery import discover_adapter_ui_extensions
from leaf.ui.components.header import create_header
from leaf.ui.constants import DEFAULT_PORT, TAB_CLASSES
from leaf.ui.tabs.adapters import create_adapters_tab
from leaf.ui.tabs.configuration import create_configuration_tab
from leaf.ui.tabs.documentation import create_documentation_tab
from leaf.ui.tabs.logs import create_logs_tab
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="interface.log")


def start_nicegui(port: int = DEFAULT_PORT, config_path: Optional[Path] = None) -> None:
    """
    Start the LEAF NiceGUI web interface.

    Creates a web-based interface for managing LEAF system configuration,
    viewing logs, managing adapters, and accessing documentation.

    Args:
        port: Port number to run the web server on (default: 8080)
        config_path: Path to the configuration file (if None, will auto-detect)
    """
    # Load markdown content and CSS from files
    curr_dir = Path(os.path.dirname(os.path.realpath(__file__)))
    markdown_dir = curr_dir / "markdown"

    with open(markdown_dir / "configuration_help.md", 'r') as f:
        config_help_md = f.read()

    with open(markdown_dir / "documentation_main.md", 'r') as f:
        docs_main_md = f.read()

    with open(markdown_dir / "documentation_protips.md", 'r') as f:
        docs_protips_md = f.read()

    with open(curr_dir / "styles.css", 'r') as f:
        custom_css = f.read()

    with open(curr_dir / "scripts.js", 'r') as f:
        custom_js = f.read()

    # Load the actual LEAF icon from images/icon.svg
    svg_path: Path = curr_dir / "images" / "icon.svg"
    favicon_b64 = "PHN2ZyB3aWR0aD0iMzIiIGhlaWdodD0iMzIiIHZpZXdCb3g9IjAgMCAzMiAzMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTggMTZDOCAxNiAxNiA8IDE2IDhDMTYgOCAyNCAxNiAyNCAxNkMyNCAxNiAxNiAyNCAxNiAyNEMxNiAyNCA4IDE2IDggMTZaIiBmaWxsPSIjNDA5NkZGIiBzdHJva2U9IiMyNTYzRUIiIHN0cm9rZS13aWR0aD0iMiIvPgo8L3N2Zz4K"

    if os.path.exists(svg_path):
        with open(svg_path, 'r') as svg_file:
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
    @ui.page('/')
    def index():
        import time
        start_time = time.time()

        try:
            logger.info("UI index page handler called - starting to build page")
            from nicegui import context as ui_context

            # Log client connection
            try:
                client_ip = ui_context.client.ip if ui_context.client else 'unknown'
                logger.info(f"Client connected from {client_ip}")
            except Exception as e:
                logger.info(f"Client connected (could not get IP: {e})")

            logger.info(f"[PERF] Client connection logged: {time.time() - start_time:.3f}s")

            # Clean up on disconnect
            def on_disconnect():
                try:
                    logger.info(f"Client disconnected")
                except Exception:
                    pass

            try:
                ui_context.client.on_disconnect(on_disconnect)
            except Exception:
                pass

            # Add custom CSS, JS, and LEAF favicon - set title here
            ui.add_head_html(f'''
                <title>LEAF - Laboratory Equipment Adapter Framework</title>
                <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}">
                <style>
                    {custom_css}
                </style>
                <script>
                    {custom_js}
                </script>
            ''')

            # Dark mode toggle
            dark = ui.dark_mode()

            # Create header
            logger.info(f"[PERF] Creating header: {time.time() - start_time:.3f}s")
            create_header(dark, curr_dir)
            logger.info(f"[PERF] Header created: {time.time() - start_time:.3f}s")

            # Enhanced tabs with icons
            with ui.tabs().classes('w-full leaf-tabs-container border-b').style('background: inherit;') as tabs:
                config_tab: ui.tab = ui.tab('Configuration', icon='settings').classes(TAB_CLASSES)
                logs_tab = ui.tab('Logs', icon='article').classes(TAB_CLASSES)
                docs_tab = ui.tab('Documentation', icon='help').classes(TAB_CLASSES)
                adapters_tab = ui.tab('Adapters', icon='extension').classes(TAB_CLASSES)

                # Dynamically create tabs for adapter UI extensions
                adapter_tabs = []
                for ext in adapter_ui_extensions:
                    ui_config = ext['ui_config']
                    tab = ui.tab(
                        ui_config['tab_name'],
                        icon=ui_config.get('tab_icon', 'extension')
                    ).classes(TAB_CLASSES)
                    adapter_tabs.append((tab, ext))
                    logger.debug(f"Created tab for adapter: {ext['adapter_code']}")

            # Attach event handler to logs tab to scroll to bottom
            logs_tab.on('click', lambda: ui.run_javascript('scrollLogToBottom()'))

            logger.info(f"[PERF] Tabs structure created: {time.time() - start_time:.3f}s")

            with ui.tab_panels(tabs, value=logs_tab).classes('w-full'):
                # Create all built-in tab panels
                logger.info(f"[PERF] Creating configuration tab: {time.time() - start_time:.3f}s")
                create_configuration_tab(config_tab, config_path)
                logger.info(f"[PERF] Configuration tab done: {time.time() - start_time:.3f}s")

                logger.info(f"[PERF] Creating logs tab: {time.time() - start_time:.3f}s")
                create_logs_tab(logs_tab)
                logger.info(f"[PERF] Logs tab done: {time.time() - start_time:.3f}s")

                logger.info(f"[PERF] Creating adapters tab: {time.time() - start_time:.3f}s")
                create_adapters_tab(adapters_tab)
                logger.info(f"[PERF] Adapters tab done: {time.time() - start_time:.3f}s")

                logger.info(f"[PERF] Creating documentation tab: {time.time() - start_time:.3f}s")
                create_documentation_tab(docs_tab, docs_main_md, docs_protips_md)
                logger.info(f"[PERF] Documentation tab done: {time.time() - start_time:.3f}s")

                # Dynamically create panels for adapter UI extensions
                logger.info(f"[PERF] Creating {len(adapter_tabs)} adapter extension tabs: {time.time() - start_time:.3f}s")
                for tab, ext in adapter_tabs:
                    try:
                        ui_config = ext['ui_config']
                        create_panel_func = ui_config['create_panel']
                        create_panel_func(tab)
                        logger.debug(f"Created panel for adapter: {ext['adapter_code']}")
                    except Exception as e:
                        logger.error(f"Error creating UI panel for adapter {ext['adapter_code']}: {e}")
                        # Create a fallback error panel
                        with ui.tab_panel(tab):
                            ui.label(f"Error loading {ext['adapter_name']} UI").classes('text-red-600')
                logger.info(f"[PERF] Adapter extension tabs done: {time.time() - start_time:.3f}s")

            logger.info(f"[PERF] LEAF UI page built successfully in {time.time() - start_time:.3f}s")

        except Exception as e:
            logger.error(f"CRITICAL: UI page handler crashed: {e}", exc_info=True)
            # Try to show error to user
            try:
                ui.label(f"Error building LEAF UI: {e}").classes('text-red-600 text-xl p-8')
                ui.label("Check logs for details. Try refreshing the page.").classes('text-body p-4')
            except:
                pass
            raise

    logger.info(f"Starting NiceGUI web interface on port {port}...")
    logger.info(f"Access the LEAF UI at http://localhost:{port}")

    try:
        ui.run(
            reload=False,
            port=port,
            show=True,
            title="LEAF - Laboratory Equipment Adapter Framework",
            reconnect_timeout=10.0  # Give clients 10 seconds to reconnect
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
