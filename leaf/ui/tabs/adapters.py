"""LEAF Adapters tab."""
import json
import os

import httpx
from nicegui import ui

from leaf.registry.discovery import get_all_adapter_codes
from leaf.ui.constants import CARD_CLASSES, CARD_WIDTH_CLASS, MARKETPLACE_URL
from leaf.ui.utils import install_adapter, uninstall_adapter
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


def build_adapters_content(container: ui.column) -> None:
    """
    Build the adapters content (installed and marketplace).

    Args:
        container: The container to build the content in
    """
    with container:
        # Installed Adapters Section
        with ui.row().classes('items-center mb-4'):
            ui.icon('inventory', size='1.5rem').classes('text-icon')
            ui.label('Installed Adapters').classes('text-xl font-semibold text-subheading ml-2')

        installed_adapters = get_all_adapter_codes()

        # Try to load marketplace data to get repo URLs for installed adapters
        marketplace_data = {}
        try:
            if os.path.exists('marketplace.json'):
                with open('marketplace.json', 'r') as f:
                    marketplace_list = json.load(f)
                    marketplace_data = {item['adapter_id']: item for item in marketplace_list}
        except Exception as e:
            logger.debug(f"Could not load marketplace data: {e}")

        if len(installed_adapters) > 0:
            with ui.row().classes('w-full flex-wrap gap-4 mb-8'):
                for installed_adapter in installed_adapters:
                    with ui.card().classes(f'{CARD_CLASSES} {CARD_WIDTH_CLASS}'):
                        with ui.card_section():
                            with ui.row().classes('items-center justify-between mb-2 w-full'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('check_circle', color='grey').classes('text-2xl')
                                    # Add clickable git icon if repo URL is available
                                    repo_url = marketplace_data.get(installed_adapter['code'], {}).get('repo_url')
                                    if repo_url:
                                        def make_repo_link(url):
                                            return lambda: ui.open(url, new_tab=True)

                                        repo_button = ui.button(
                                            icon='code',
                                            on_click=make_repo_link(repo_url)
                                        ).props('flat dense round').classes('text-grey')
                                        repo_button.tooltip('View repository')
                                ui.chip('INSTALLED', color='grey')
                            ui.label(installed_adapter['code']).classes('text-lg font-bold text-heading mb-1')
                            ui.label(installed_adapter['name']).classes('text-sm text-body mb-3')

                            def make_uninstall_handler(adapter):
                                return lambda: uninstall_adapter(adapter)

                            ui.button('Uninstall',
                                    icon='delete',
                                    on_click=make_uninstall_handler(installed_adapter)).classes(
                                'btn-tertiary w-full rounded-lg transition-colors'
                            )
        else:
            with ui.card().classes('bg-info-card border border-default p-4 mb-8'):
                with ui.row().classes('items-center'):
                    ui.icon('warning', color='grey').classes('text-2xl mr-2')
                    ui.label('No adapters installed. Install adapters from the marketplace below.').classes('text-body')

        ui.separator().classes('my-6')

        # Available Adapters Section
        with ui.row().classes('items-center mb-4'):
            ui.icon('store', size='1.5rem').classes('text-icon')
            ui.label('Adapter Marketplace').classes('text-xl font-semibold text-subheading ml-2')

        # Container for marketplace adapters
        marketplace_container = ui.column().classes('w-full')

        # Show loading indicator
        with marketplace_container:
            loading_label = ui.label('Loading marketplace...').classes('text-body')
            loading_spinner = ui.spinner(size='lg')

        # Load marketplace data asynchronously
        async def load_marketplace():
            try:
                url = MARKETPLACE_URL
                logger.debug(f"Fetching marketplace data from {url}")
                # Use async httpx client with timeout
                async with httpx.AsyncClient(timeout=5.0) as client:
                    if os.path.exists('marketplace.json'):
                        data = json.load(open('marketplace.json'))
                    else:
                        response = await client.get(url)
                        data = response.json()
                        # Write to file
                        with open('marketplace.json', 'w') as f:
                            f.write(response.text)

                logger.debug(f"Marketplace data fetched successfully, found {len(data)} adapters")

                # Remove loading indicator
                loading_label.delete()
                loading_spinner.delete()

                with marketplace_container:
                    with ui.row().classes('w-full flex-wrap gap-4'):
                        for adapter in data:
                            # Check if adapter is installed
                            logger.debug(f"Checking if {adapter['adapter_id']} is installed...")
                            installed = False
                            for installed_adapter in installed_adapters:
                                if adapter['adapter_id'] == installed_adapter['code']:
                                    logger.debug(f"Adapter {adapter['adapter_id']} is installed, skipping in installer view")
                                    installed = True
                            if not installed:
                                with ui.card().classes(f'{CARD_CLASSES} {CARD_WIDTH_CLASS}'):
                                    with ui.card_section():
                                        with ui.row().classes('items-center justify-between mb-2 w-full'):
                                            with ui.row().classes('items-center gap-2'):
                                                ui.icon('cloud_download', color='grey').classes('text-2xl')
                                                # Add clickable git icon for repository
                                                repo_url = adapter.get('repo_url')
                                                if repo_url:
                                                    def make_repo_link(url):
                                                        return lambda: ui.open(url, new_tab=True)

                                                    repo_button = ui.button(
                                                        icon='code',
                                                        on_click=make_repo_link(repo_url)
                                                    ).props('flat dense round').classes('text-grey')
                                                    repo_button.tooltip('View repository')
                                            ui.chip('AVAILABLE', color='grey')
                                        ui.label(adapter['adapter_id']).classes('text-lg font-bold text-heading mb-1')
                                        ui.label(adapter.get('name', 'No description')).classes('text-sm text-body mb-3')

                                        def make_install_handler(adptr):
                                            return lambda: install_adapter(adptr)

                                        ui.button('Install',
                                                icon='download',
                                                on_click=make_install_handler(adapter)).classes(
                                            'btn-secondary w-full rounded-lg transition-colors'
                                        )
            except Exception as e:
                logger.error(f"Failed to load marketplace: {e}", exc_info=True)
                # Remove loading indicator
                loading_label.delete()
                loading_spinner.delete()
                with marketplace_container:
                    with ui.card().classes('bg-info-card border border-default p-4'):
                        with ui.row().classes('items-center'):
                            ui.icon('error', color='grey').classes('text-2xl mr-2')
                            ui.label(f'Unable to load marketplace: {str(e)}').classes('text-body')

        # Trigger async load
        ui.timer(0.1, load_marketplace, once=True)


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
    button.props('loading')
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
            ui.notify(f"Found {len(newly_registered)} new adapter(s): {', '.join(newly_registered)}",
                     type='positive', position='top', close_button=True, timeout=5000)
            logger.info(f"New adapters registered: {newly_registered}")

            # If new adapters have UI extensions, offer to reload the page
            if new_ui_extensions_found:
                new_extensions = [ext for ext in ui_extensions if ext not in old_ui_extensions]
                extension_names = [ext['adapter_name'] for ext in new_extensions]

                with ui.dialog() as reload_dialog, ui.card():
                    ui.label('New Adapter Tabs Available').classes('text-xl font-bold mb-4')
                    ui.label(f'The following adapter(s) provide custom UI tabs:').classes('mb-2')
                    for name in extension_names:
                        ui.label(f'• {name}').classes('ml-4')
                    ui.label('Reload the page to see the new tabs?').classes('mt-4 mb-4')

                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancel', on_click=reload_dialog.close).classes('btn-tertiary')
                        ui.button('Reload Page', icon='refresh',
                                 on_click=lambda: ui.navigate.reload()).classes('btn-primary')

                reload_dialog.open()
        else:
            ui.notify("No new adapters found", type='info', position='top')
            logger.info("No new adapters found during refresh")

        # Clear and rebuild the content
        container.clear()
        build_adapters_content(container)

    except Exception as e:
        logger.error(f"Error refreshing adapters: {e}", exc_info=True)
        ui.notify(f"Error refreshing adapters: {str(e)}", type='negative', position='top')
    finally:
        # Re-enable button
        button.props(remove='loading')
        button.enable()


def create_adapters_tab(adapters_tab: ui.tab) -> None:
    """
    Create the adapters tab panel.

    Args:
        adapters_tab: The tab component this panel belongs to
    """
    with ui.tab_panel(adapters_tab).classes('w-full p-6'):
        with ui.card().classes('leaf-card w-full'):
            with ui.card_section():
                with ui.row().classes('items-center justify-between mb-6 w-full'):
                    with ui.row().classes('items-center'):
                        ui.icon('extension', size='2rem').classes('text-icon')
                        ui.label('LEAF Adapter Management').classes('text-2xl font-bold text-heading ml-2')

                    # Add refresh button
                    refresh_button = ui.button(
                        'Refresh',
                        icon='refresh',
                        on_click=lambda: refresh_adapters_ui(content_container, refresh_button)
                    ).classes('btn-secondary')
                    refresh_button.tooltip('Scan for newly installed adapters')

                # Content container that can be refreshed
                content_container = ui.column().classes('w-full')

                # Build the initial content
                build_adapters_content(content_container)
