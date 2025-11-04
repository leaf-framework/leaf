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


def create_adapters_tab(adapters_tab: ui.tab) -> None:
    """
    Create the adapters tab panel.

    Args:
        adapters_tab: The tab component this panel belongs to
    """
    with ui.tab_panel(adapters_tab).classes('w-full p-6'):
        with ui.card().classes('leaf-card w-full'):
            with ui.card_section():
                with ui.row().classes('items-center mb-6'):
                    ui.icon('extension', size='2rem').classes('text-icon')
                    ui.label('LEAF Adapter Management').classes('text-2xl font-bold text-heading ml-2')

                # Installed Adapters Section
                with ui.row().classes('items-center mb-4'):
                    ui.icon('inventory', size='1.5rem').classes('text-icon')
                    ui.label('Installed Adapters').classes('text-xl font-semibold text-subheading ml-2')

                installed_adapters = get_all_adapter_codes()
                if len(installed_adapters) > 0:
                    with ui.row().classes('w-full flex-wrap gap-4 mb-8'):
                        for installed_adapter in installed_adapters:
                            with ui.card().classes(f'{CARD_CLASSES} {CARD_WIDTH_CLASS}'):
                                with ui.card_section():
                                    with ui.row().classes('items-center justify-between mb-2'):
                                        ui.icon('check_circle', color='grey').classes('text-2xl')
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

                # Load marketplace data asynchronously to avoid blocking page load
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
                                                with ui.row().classes('items-center justify-between mb-2'):
                                                    ui.icon('cloud_download', color='grey').classes('text-2xl')
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
