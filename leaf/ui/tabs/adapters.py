"""LEAF Adapters tab."""

from pathlib import Path

import httpx
import yaml
from nicegui import ui

from leaf.registry.discovery import get_all_adapter_codes
from leaf.ui.constants import CARD_CLASSES, CARD_WIDTH_CLASS, MARKETPLACE_URL
from leaf.ui.utils import install_adapter, uninstall_adapter
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


def format_key(key: str) -> str:
    """Format a key string for display (e.g., 'device_type' -> 'Device Type')."""
    return key.replace("_", " ").title()


def show_adapter_details(adapter: dict) -> None:
    """
    Show a dialog with detailed information about an adapter.

    Args:
        adapter: The adapter data dictionary
    """
    name = adapter.get("name", adapter.get("adapter_id", "Unknown"))
    equipment = adapter.get("equipment_data", adapter)
    repo_url = adapter.get("repo_url")

    with ui.dialog() as dialog, ui.card().classes("w-[600px] max-h-[80vh]"):
        # Header
        with ui.row().classes("items-center justify-between w-full mb-4"):
            ui.label(name).classes("text-xl font-bold text-heading")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        with ui.scroll_area().classes("w-full max-h-[60vh]"):
            # Description section
            ui.label("Description").classes("text-lg font-semibold text-subheading border-b pb-2 mb-2")
            description = adapter.get("description", "No description available.")
            ui.label(description).classes("text-body mb-4")

            # Basic Information section
            ui.label("Basic Information").classes("text-lg font-semibold text-subheading border-b pb-2 mb-2")
            with ui.grid(columns=2).classes("gap-2 mb-4"):
                ui.label("Adapter ID:").classes("font-medium")
                ui.label(adapter.get("adapter_id", "N/A")).classes("font-mono bg-gray-100 px-2 rounded")

                if equipment.get("version"):
                    ui.label("Version:").classes("font-medium")
                    ui.label(equipment.get("version"))

                if equipment.get("manufacturer"):
                    ui.label("Manufacturer:").classes("font-medium")
                    ui.label(equipment.get("manufacturer"))

                if equipment.get("device_type"):
                    ui.label("Device Type:").classes("font-medium")
                    ui.label(equipment.get("device_type"))

                if equipment.get("application"):
                    ui.label("Application:").classes("font-medium")
                    ui.label(equipment.get("application"))

            # Features section (if available)
            if equipment.get("features"):
                ui.label("Features").classes("text-lg font-semibold text-subheading border-b pb-2 mb-2")
                with ui.column().classes("mb-4"):
                    for key, value in equipment["features"].items():
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("check_circle", color="green").classes("text-sm")
                            ui.label(f"{format_key(key)}: {value}").classes("text-body")

            # Specifications section (other equipment data)
            exclude_keys = {
                "version",
                "manufacturer",
                "device_type",
                "application",
                "features",
                "requirements",
                "type",
                "class",
            }
            other_data = {k: v for k, v in equipment.items() if k not in exclude_keys}
            if other_data:
                ui.label("Specifications").classes("text-lg font-semibold text-subheading border-b pb-2 mb-2")
                with ui.grid(columns=2).classes("gap-2 mb-4"):
                    for key, value in other_data.items():
                        ui.label(f"{format_key(key)}:").classes("font-medium")
                        if isinstance(value, dict):
                            ui.label(str(value)).classes("font-mono text-sm bg-gray-100 px-2 rounded")
                        else:
                            ui.label(str(value))

            # Requirements section
            requirements = adapter.get("requirements", equipment.get("requirements"))
            if requirements and isinstance(requirements, dict) and len(requirements) > 0:
                ui.label("Requirements").classes("text-lg font-semibold text-subheading border-b pb-2 mb-2")
                with ui.grid(columns=2).classes("gap-2 mb-4"):
                    for key, value in requirements.items():
                        ui.label(f"{format_key(key)}:").classes("font-medium")
                        ui.label(str(value)).classes("font-mono bg-gray-100 px-2 rounded")

            # Installation section
            if repo_url:
                ui.label("Installation").classes("text-lg font-semibold text-subheading border-b pb-2 mb-2")
                ui.label("Install this adapter using PIP:").classes("text-body mb-2")
                with ui.card().classes("bg-gray-100 p-3 mb-2"):
                    ui.label(f"pip install git+{repo_url}").classes("font-mono text-sm")
                ui.label("This will add the adapter to your LEAF installation.").classes("text-sm text-gray-500")

        # Footer with repository link
        with ui.row().classes("w-full justify-end mt-4 pt-4 border-t"):
            if repo_url:
                ui.button(
                    "View Repository",
                    icon="public",
                    on_click=lambda url=repo_url: ui.run_javascript(f'window.open("{url}", "_blank")'),
                ).classes("btn-secondary")
            ui.button("Close", on_click=dialog.close).classes("btn-tertiary")

    dialog.open()


# Cache location for downloaded marketplace
CACHE_DIR = Path.home() / ".cache" / "leaf"
CACHE_FILE = CACHE_DIR / "marketplace.yaml"


def get_bundled_marketplace_path() -> Path:
    """
    Get the path to the bundled marketplace.yaml file.

    Returns:
        Path to the bundled marketplace file
    """
    # The bundled file is in leaf/data/marketplace.yaml
    return Path(__file__).parent.parent / "data" / "marketplace.yaml"


def load_bundled_marketplace() -> list | None:
    """
    Load marketplace data from the bundled file.

    Returns:
        Marketplace data as a list, or None if file doesn't exist
    """
    try:
        bundled_path = get_bundled_marketplace_path()
        if bundled_path.exists():
            with open(bundled_path) as f:
                data = yaml.safe_load(f)
            logger.debug(f"Loaded bundled marketplace data from {bundled_path}")
            return data
    except Exception as e:
        logger.warning(f"Failed to load bundled marketplace: {e}")
    return None


def build_adapters_content(container: ui.column) -> None:
    """
    Build the adapters content (installed and marketplace).

    Args:
        container: The container to build the content in
    """
    with container:
        # Installed Adapters Section
        with ui.row().classes("items-center mb-4"):
            ui.icon("inventory", size="1.5rem").classes("text-icon")
            ui.label("Installed Adapters").classes("text-xl font-semibold text-subheading ml-2")

        installed_adapters = get_all_adapter_codes()

        # Try to load marketplace data to get repo URLs for installed adapters
        marketplace_data = {}
        try:
            if CACHE_FILE.exists():
                with open(CACHE_FILE) as f:
                    marketplace_list = yaml.safe_load(f)
                    marketplace_data = {item["adapter_id"]: item for item in marketplace_list}
            else:
                # Try bundled marketplace as fallback
                marketplace_list = load_bundled_marketplace()
                if marketplace_list:
                    marketplace_data = {item["adapter_id"]: item for item in marketplace_list}
        except Exception as e:
            logger.debug(f"Could not load marketplace data: {e}")

        if len(installed_adapters) > 0:
            with ui.row().classes("w-full flex-wrap gap-4 mb-8"):
                for installed_adapter in installed_adapters:
                    with ui.card().classes(f"{CARD_CLASSES} {CARD_WIDTH_CLASS}"), ui.card_section():
                        # Get full adapter data from marketplace for details
                        adapter_data = marketplace_data.get(installed_adapter["code"], {})
                        repo_url = adapter_data.get("repo_url")

                        def make_details_handler(adptr_data, adptr_info):
                            # Merge installed adapter info with marketplace data
                            merged = {**adptr_data, "adapter_id": adptr_info["code"], "name": adptr_info["name"]}
                            return lambda: show_adapter_details(merged)

                        def make_repo_link(url):
                            return lambda: ui.run_javascript(f'window.open("{url}", "_blank")')

                        with ui.row().classes("items-center justify-between mb-2 w-full"):
                            with ui.row().classes("items-center gap-2"):
                                # Add clickable info icon for details
                                info_button = (
                                    ui.button(
                                        icon="info", on_click=make_details_handler(adapter_data, installed_adapter)
                                    )
                                    .props("flat dense round")
                                    .classes("text-blue")
                                )
                                info_button.tooltip("More info")
                                # Add clickable git icon if repo URL is available
                                if repo_url:
                                    repo_button = (
                                        ui.button(icon="public", on_click=make_repo_link(repo_url))
                                        .props("flat dense round")
                                        .classes("text-blue")
                                    )
                                    repo_button.tooltip("View repository")
                        ui.label(installed_adapter["code"]).classes("text-lg font-bold text-heading mb-1")
                        ui.label(installed_adapter["name"]).classes("text-sm text-body mb-3")

                        def make_uninstall_handler(adapter):
                            return lambda: uninstall_adapter(adapter)

                        ui.button(
                            "Uninstall", icon="delete", on_click=make_uninstall_handler(installed_adapter)
                        ).classes("btn-tertiary w-full rounded-lg transition-colors")
        else:
            with ui.card().classes("bg-info-card border border-default p-4 mb-8"):
                with ui.row().classes("items-center"):
                    ui.icon("warning", color="grey").classes("text-2xl mr-2")
                    ui.label("No adapters installed. Install adapters from the marketplace below.").classes("text-body")

        ui.separator().classes("my-6")

        # Available Adapters Section
        with ui.row().classes("items-center mb-4"):
            ui.icon("store", size="1.5rem").classes("text-icon")
            ui.label("Adapter Marketplace").classes("text-xl font-semibold text-subheading ml-2")

        # Container for marketplace adapters
        marketplace_container = ui.column().classes("w-full")

        # Show loading indicator
        with marketplace_container:
            loading_label = ui.label("Loading marketplace...").classes("text-body")
            loading_spinner = ui.spinner(size="lg")

        # Load marketplace data asynchronously
        async def load_marketplace():
            data = None
            cache_is_fresh = False

            try:
                url = MARKETPLACE_URL

                # Check if cache exists and is fresh (< 30 days)
                if CACHE_FILE.exists():
                    from datetime import datetime, timedelta

                    cache_age = datetime.now() - datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)
                    cache_is_fresh = cache_age < timedelta(days=30)

                    if cache_is_fresh:
                        logger.debug(f"Loading fresh cached marketplace from {CACHE_FILE}")
                        with open(CACHE_FILE) as f:
                            data = yaml.safe_load(f)

                # If no fresh cache, start with bundled file
                if not cache_is_fresh:
                    logger.debug("Cache is stale or missing, loading bundled marketplace")
                    data = load_bundled_marketplace()

                    # Try to download fresh version to cache for next time
                    try:
                        logger.debug(f"Attempting to download fresh marketplace from {url}")
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            response = await client.get(url)
                            response.raise_for_status()
                            fresh_data = yaml.safe_load(response.text)

                            # Cache the downloaded data
                            CACHE_DIR.mkdir(parents=True, exist_ok=True)
                            with open(CACHE_FILE, "w") as f:
                                f.write(response.text)
                            logger.info(f"Downloaded and cached fresh marketplace data to {CACHE_FILE}")

                            # Use the fresh downloaded data
                            data = fresh_data
                    except Exception as download_error:
                        logger.warning(f"Could not download fresh marketplace: {download_error}")
                        if not data:
                            raise Exception("No bundled marketplace available and download failed")

                if data:
                    logger.debug(f"Marketplace data loaded successfully, found {len(data)} adapters")

                # Remove loading indicator
                loading_label.delete()
                loading_spinner.delete()

                with marketplace_container, ui.row().classes("w-full flex-wrap gap-4"):
                    for adapter in data:
                        # Check if adapter is installed
                        logger.debug(f"Checking if {adapter['adapter_id']} is installed...")
                        installed = False
                        for installed_adapter in installed_adapters:
                            if adapter["adapter_id"] == installed_adapter["code"]:
                                logger.debug(
                                    f"Adapter {adapter['adapter_id']} is installed, skipping in installer view"
                                )
                                installed = True
                        if not installed:
                            with ui.card().classes(f"{CARD_CLASSES} {CARD_WIDTH_CLASS}"):
                                with ui.card_section():
                                    repo_url = adapter.get("repo_url")

                                    def make_details_handler(adptr):
                                        return lambda: show_adapter_details(adptr)

                                    def make_repo_link(url):
                                        return lambda: ui.run_javascript(f'window.open("{url}", "_blank")')

                                    with ui.row().classes("items-center justify-between mb-2 w-full"):
                                        with ui.row().classes("items-center gap-2"):
                                            # Add clickable info icon for details
                                            info_button = (
                                                ui.button(icon="info", on_click=make_details_handler(adapter))
                                                .props("flat dense round")
                                                .classes("text-blue")
                                            )
                                            info_button.tooltip("More info")
                                            # Add clickable git icon for repository
                                            if repo_url:
                                                repo_button = (
                                                    ui.button(icon="public", on_click=make_repo_link(repo_url))
                                                    .props("flat dense round")
                                                    .classes("text-blue")
                                                )
                                                repo_button.tooltip("View repository")
                                    ui.label(adapter["adapter_id"]).classes("text-lg font-bold text-heading mb-1")
                                    ui.label(adapter.get("name", "No description")).classes("text-sm text-body mb-3")

                                    def make_install_handler(adptr):
                                        return lambda: install_adapter(adptr)

                                    ui.button(
                                        "Install", icon="download", on_click=make_install_handler(adapter)
                                    ).classes("btn-secondary w-full rounded-lg transition-colors")
            except Exception as e:
                logger.error(f"Failed to load marketplace: {e}", exc_info=True)
                # Remove loading indicator
                loading_label.delete()
                loading_spinner.delete()
                with marketplace_container, ui.card().classes("bg-info-card border border-default p-4"):
                    with ui.row().classes("items-center"):
                        ui.icon("error", color="grey").classes("text-2xl mr-2")
                        ui.label(f"Unable to load marketplace: {str(e)}").classes("text-body")

        # Trigger async load
        ui.timer(0.1, load_marketplace, once=True)


async def force_refresh_marketplace(container: ui.column) -> None:
    """
    Force refresh the marketplace by downloading fresh data, then replacing the cache.

    Args:
        container: The container to refresh
    """
    try:
        ui.notify("Downloading fresh marketplace data...", type="info", position="top")
        logger.info(f"Force refreshing marketplace from {MARKETPLACE_URL}")

        # Try to download fresh marketplace data
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(MARKETPLACE_URL)
            response.raise_for_status()
            fresh_data = yaml.safe_load(response.text)

            # Validate the data looks correct
            if not isinstance(fresh_data, list) or len(fresh_data) == 0:
                raise ValueError("Downloaded marketplace data is empty or invalid")

            # Download successful - now replace the cache
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                f.write(response.text)

            logger.info(f"Successfully downloaded and cached {len(fresh_data)} adapters to {CACHE_FILE}")
            ui.notify(f"Marketplace updated: {len(fresh_data)} adapters available", type="positive", position="top")

        # Clear and rebuild the content with the new data
        container.clear()
        build_adapters_content(container)

    except httpx.HTTPError as e:
        logger.error(f"Failed to download marketplace: {e}", exc_info=True)
        ui.notify(f"Download failed: {str(e)}. Using cached data.", type="warning", position="top")
    except Exception as e:
        logger.error(f"Error force refreshing marketplace: {e}", exc_info=True)
        ui.notify(f"Error: {str(e)}", type="negative", position="top")


def refresh_adapters_ui(container: ui.column, button: ui.button) -> None:
    """
    Refresh the adapters UI by re-discovering adapters.

    Args:
        container: The container to refresh
        button: The refresh button to update state
    """
    from leaf.registry.discovery import refresh_adapter_discovery
    from leaf.registry.registry import refresh_equipment_from_discovery

    # Disable button and show loading state
    button.props("loading")
    button.disable()

    try:
        # Store current UI extensions count before refresh
        from leaf.registry.discovery import discover_adapter_ui_extensions

        old_ui_extensions = discover_adapter_ui_extensions()
        old_extension_count = len(old_ui_extensions)

        # Refresh the adapter discovery and registry
        logger.info("Refreshing adapter discovery from UI...")
        all_adapters, ui_extensions = refresh_adapter_discovery()
        newly_registered = refresh_equipment_from_discovery()

        # Check if new UI extensions were found
        new_ui_extensions_found = len(ui_extensions) > old_extension_count

        # Notify user
        if newly_registered:
            ui.notify(
                f"Found {len(newly_registered)} new adapter(s): {', '.join(newly_registered)}",
                type="positive",
                position="top",
                close_button=True,
                timeout=5000,
            )
            logger.info(f"New adapters registered: {newly_registered}")

            # If new adapters have UI extensions, offer to reload the page
            if new_ui_extensions_found:
                new_extensions = [ext for ext in ui_extensions if ext not in old_ui_extensions]
                extension_names = [ext["adapter_name"] for ext in new_extensions]

                with ui.dialog() as reload_dialog, ui.card():
                    ui.label("New Adapter Tabs Available").classes("text-xl font-bold mb-4")
                    ui.label("The following adapter(s) provide custom UI tabs:").classes("mb-2")
                    for name in extension_names:
                        ui.label(f"• {name}").classes("ml-4")
                    ui.label("Reload the page to see the new tabs?").classes("mt-4 mb-4")

                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Cancel", on_click=reload_dialog.close).classes("btn-tertiary")
                        ui.button("Reload Page", icon="refresh", on_click=lambda: ui.navigate.reload()).classes(
                            "btn-primary"
                        )

                reload_dialog.open()
        else:
            ui.notify("No new adapters found", type="info", position="top")
            logger.info("No new adapters found during refresh")

        # Clear and rebuild the content
        container.clear()
        build_adapters_content(container)

    except Exception as e:
        logger.error(f"Error refreshing adapters: {e}", exc_info=True)
        ui.notify(f"Error refreshing adapters: {str(e)}", type="negative", position="top")
    finally:
        # Re-enable button
        button.props(remove="loading")
        button.enable()


def create_adapters_tab(adapters_tab: ui.tab) -> None:
    """
    Create the adapters tab panel.

    Args:
        adapters_tab: The tab component this panel belongs to
    """
    with ui.tab_panel(adapters_tab).classes("w-full p-6"), ui.card().classes("leaf-card w-full"), ui.card_section():
        with ui.row().classes("items-center justify-between mb-6 w-full"):
            with ui.row().classes("items-center"):
                ui.icon("extension", size="2rem").classes("text-icon")
                ui.label("LEAF Adapter Management").classes("text-2xl font-bold text-heading ml-2")

            # Add refresh buttons
            with ui.row().classes("gap-2"):
                refresh_button = ui.button(
                    "Refresh Adapters",
                    icon="refresh",
                    on_click=lambda: refresh_adapters_ui(content_container, refresh_button),
                ).classes("btn-secondary")
                refresh_button.tooltip("Scan for newly installed adapters")

                force_refresh_button = ui.button(
                    "Force Refresh Marketplace",
                    icon="cloud_download",
                    on_click=lambda: force_refresh_marketplace(content_container),
                ).classes("btn-tertiary")
                force_refresh_button.tooltip("Clear cache and download fresh marketplace data")

        # Content container that can be refreshed
        content_container = ui.column().classes("w-full")

        # Build the initial content
        build_adapters_content(content_container)
