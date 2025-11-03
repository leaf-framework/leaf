"""LEAF Configuration tab."""

import os
import sys
from functools import partial
from pathlib import Path
from typing import Optional

from nicegui import ui

from leaf.registry.discovery import get_all_adapter_codes
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


def create_configuration_tab(config_tab: ui.tab, config_path: Optional[Path]) -> None:
    """
    Create the configuration tab panel.

    Args:
        config_tab: The tab component this panel belongs to
        config_path: Path to the configuration file (if None, will auto-detect)
    """
    global leaf
    with ui.tab_panel(config_tab).classes('w-full h-full'):
        # Header section
        with ui.row().classes('items-center mb-6 px-6 pt-6'):
             ui.icon('settings', size='2rem').classes('text-icon')
             ui.label('LEAF Configuration').classes('text-2xl font-bold text-heading ml-2')

        # Code editor for YAML
        # Use the passed config_path if available, otherwise auto-detect
        if config_path is None:
            import leaf.start
            leaf_start_dir = Path(os.path.dirname(os.path.realpath(leaf.start.__file__)))
            configuration_path: Path = leaf_start_dir / 'config' / 'configuration.yaml'
        else:
            configuration_path = config_path

        logger.info(f"Configuration tab using file: {configuration_path}")
        if os.path.exists(configuration_path):
            with open(configuration_path, 'r') as file:
                config_yaml = file.read()
        else:
            logger.error("Configuration file not found")
            config_yaml = '''# No configuration file found'''

        # Full width layout for editor and help - using flex to prevent wrapping
        with ui.row().classes('w-full px-6 flex flex-nowrap'):
            # Configuration editor - Left side (flexible, takes remaining space)
            with ui.column().classes('flex-1 min-w-0 mr-6'):
                ui.label('Configuration Editor').classes('text-lg font-semibold mb-3 text-heading')
                with ui.card().classes('leaf-card h-96 w-full overflow-hidden'):
                    with ui.card_section().classes('p-0 w-full h-full'):
                        editor = ui.codemirror(value=config_yaml, language="YAML", theme='basicDark').classes('w-full h-full')

            # Help section - Right side (fixed width, no shrink)
            with ui.column().classes('w-[35%] flex-shrink-0'):
                ui.label('Adapter Help').classes('text-lg font-semibold mb-3 text-heading')

                # Dropdown to select adapter
                adapter_select = ui.select(
                    options=[],
                    label='Select an adapter for help',
                    with_input=True
                ).classes('w-full mb-3')

                # Help text display area
                help_container = ui.column().classes('w-full')

                with help_container:
                    with ui.card().classes('bg-info-card border border-default h-80 overflow-y-auto shadow-sm p-4'):
                        help_text = ui.markdown('Select an adapter from the dropdown to see configuration examples.').classes('text-sm text-body-secondary')

                # Load adapters when dropdown is opened
                def load_adapters():
                    logger.info("Loading adapters for help interface")
                    try:
                        adapter_codes = get_all_adapter_codes()
                        if adapter_codes:
                            # Create options dict with adapter code as key and display name as value
                            adapter_select.options = {
                                adapter['code']: f"{adapter['code']} - {adapter['name']}"
                                for adapter in adapter_codes
                            }
                            adapter_select.update()
                            logger.info(f"Loaded {len(adapter_codes)} adapters")
                        else:
                            logger.warning("No adapters found")
                    except Exception as e:
                        logger.error(f"Failed to load adapters: {e}", exc_info=True)

                # Show help for selected adapter
                def show_adapter_help(e):
                    selected = adapter_select.value
                    if not selected:
                        return

                    logger.info(f"Showing help for adapter: {selected}")

                    try:
                        # Find the adapter module and read its example.yaml
                        adapter_codes = get_all_adapter_codes()
                        adapter_info = next((a for a in adapter_codes if a['code'] == selected), None)

                        if not adapter_info:
                            logger.error(f"Adapter {selected} not found in adapter list")
                            help_text.set_content(f"Error: Adapter {selected} not found")
                            return

                        # Get the module path from the adapter class
                        adapter_class = adapter_info.get('class')
                        if not adapter_class:
                            logger.error(f"Adapter {selected} has no class information")
                            help_text.set_content(f"Error: No class information for {selected}")
                            return

                        # Find the directory where the adapter is installed
                        import inspect
                        adapter_module = inspect.getmodule(adapter_class)
                        if not adapter_module or not adapter_module.__file__:
                            logger.error(f"Could not find module file for {selected}")
                            help_text.set_content(f"Error: Could not locate adapter files for {selected}")
                            return

                        adapter_dir = os.path.dirname(adapter_module.__file__)
                        example_yaml_path = os.path.join(adapter_dir, 'example.yaml')

                        logger.info(f"Looking for example.yaml at: {example_yaml_path}")

                        if os.path.exists(example_yaml_path):
                            # Read the actual example.yaml
                            with open(example_yaml_path, 'r') as f:
                                example_content = f.read()
                                # Load yaml to get the pretty-printed version
                                import yaml
                                yaml_content = yaml.safe_load(example_content)
                                # Remove OUTPUTS
                                del yaml_content['OUTPUTS']
                                example_content = yaml.dump(yaml_content, indent=2)

                            help_md = f"""### {selected} Adapter Configuration

**Configuration Example from adapter:**

```yaml
{example_content}
```

**Note:** This is the official example from the `{selected}` adapter.
Adjust values like `instance_id`, `institute`, etc. to match your setup.

**Path:** `{example_yaml_path}`
"""
                        else:
                            # Fallback if example.yaml doesn't exist
                            logger.warning(f"No example.yaml found at {example_yaml_path}")
                            help_md = f"""### {selected} Adapter Configuration

**No example.yaml found for this adapter.**

The adapter is installed at: `{adapter_dir}`

**Generic Configuration Template:**

```yaml
EQUIPMENT_INSTANCES:
  - equipment:
      adapter: {selected}
      data:
        instance_id: my_device_001
        institute: my_lab
        experiment_id: experiment_123
      requirements:
        interval: 1
```

**Tip:** Check the adapter documentation or repository for specific configuration requirements.
"""

                        help_text.set_content(help_md)

                    except Exception as e:
                        logger.error(f"Error loading help for {selected}: {e}", exc_info=True)
                        help_text.set_content(f"""### Error Loading Adapter Help

Could not load configuration example for `{selected}`.

**Error:** {str(e)}

Check the logs for more details.
""")

                adapter_select.on('focus', load_adapters)
                adapter_select.on('update:model-value', show_adapter_help)

        # Button to start/restart the adapters
        def restart_app(restart: bool) -> None:
            # Write new configuration to file
            if restart:
                abs_path = os.path.abspath(configuration_path)
                logger.info(f"Saving configuration to: {abs_path}")
                logger.debug(f"Configuration content length: {len(editor.value)} characters")

                # Log first 200 chars to see what's being saved
                preview = editor.value[:200].replace('\n', '\\n')
                logger.info(f"Configuration preview (first 200 chars): {preview}")

                try:
                    with open(configuration_path, 'w') as config_file:
                        config_file.write(editor.value)
                    logger.info(f"Configuration saved successfully to {abs_path}")

                    # Verify what was actually written
                    with open(configuration_path, 'r') as verify_file:
                        written_content = verify_file.read()
                    logger.info(f"Verification: File now contains {len(written_content)} characters")
                    logger.debug(f"Verification preview: {written_content[:200].replace(chr(10), '\\n')}")
                    ui.notify(
                        f'Configuration saved to {os.path.basename(abs_path)}! Restarting...',
                        icon='check_circle',
                        color='positive',
                        timeout=2000
                    )
                    logger.info("Restarting LEAF with saved configuration...")
                    # Give the notification time to display
                    import time
                    time.sleep(0.5)
                    os.execl(sys.executable, sys.executable, *sys.argv)
                except Exception as e:
                    logger.error(f"Failed to save configuration: {e}", exc_info=True)
                    ui.notify(f'Error saving configuration: {e}', icon='error', color='negative')
            else:
                # Close the current window and shutdown the app
                ui.notify('Stopping LEAF system...', icon='power_settings_new', color='negative')
                logger.info("Stopping LEAF system...")
                ui.run_javascript('window.open(location.href, "_self", "");window.close()')
                os.execl(sys.executable, sys.executable, sys.argv[0], "--shutdown")

        # Action buttons at the bottom - aligned with tab headers
        with ui.row().classes('w-full gap-4 py-4 border-t border-default bg-panel-light pl-4'):
            ui.button('Save & Restart', icon='save', on_click=partial(restart_app, True)).classes('btn-primary px-6 py-3 rounded-lg transition-colors shadow-md')
            ui.button('Stop App', icon='stop', on_click=partial(restart_app, False)).classes('btn-danger px-6 py-3 rounded-lg transition-colors shadow-md')
