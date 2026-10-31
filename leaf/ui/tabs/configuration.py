"""LEAF Configuration tab."""

import os
from pathlib import Path

from nicegui import ui

from leaf.registry.discovery import get_all_adapter_codes
from leaf.ui.components.app_control import restart_leaf
from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="input_module.log")


def read_adapter_readme(adapter_dir: str) -> str:
    """Extra help (requirements, control messages) an adapter ships as README.md in its package, or ""."""
    readme_path = os.path.join(adapter_dir, "README.md")
    if not os.path.exists(readme_path):
        return ""
    with open(readme_path) as f:
        return "\n" + f.read()


def create_configuration_tab(config_tab: ui.tab, config_path: Path | None) -> None:
    """
    Create the configuration tab panel.

    Args:
        config_tab: The tab component this panel belongs to
        config_path: Path to the configuration file (if None, will auto-detect)
    """
    global leaf
    with ui.tab_panel(config_tab).classes("w-full h-full"):
        # Header section
        with ui.row().classes("items-center mb-6 px-6 pt-6"):
            ui.icon("settings", size="2rem").classes("text-icon")
            ui.label("LEAF Configuration").classes("text-2xl font-bold text-heading ml-2")

        # Code editor for YAML
        # Use the passed config_path if available, otherwise auto-detect
        if config_path is None:
            import leaf.start

            leaf_start_dir = Path(os.path.dirname(os.path.realpath(leaf.start.__file__)))
            configuration_path: Path = leaf_start_dir / "config" / "configuration.yaml"
        else:
            configuration_path = config_path

        logger.debug(f"Configuration tab using file: {configuration_path}")
        if os.path.exists(configuration_path):
            with open(configuration_path) as file:
                config_yaml = file.read()
        else:
            logger.error("Configuration file not found")
            config_yaml = """# No configuration file found"""

        # Editor and help fill the window height; 300px leaves room for the header, title and Save button
        with ui.row().classes("w-full px-6 flex flex-nowrap h-[calc(100vh-300px)] min-h-96"):
            # Configuration editor - Left half
            with ui.column().classes("flex-1 min-w-0 mr-6 h-full"):
                ui.label("Configuration Editor").classes("text-lg font-semibold mb-3 text-heading")
                with ui.card().classes("leaf-card flex-grow min-h-0 w-full overflow-hidden"):
                    with ui.card_section().classes("p-0 w-full h-full"):
                        editor = ui.codemirror(value=config_yaml, language="YAML", theme="basicDark").classes(
                            "w-full h-full"
                        )

            # Help section - Right side, same width as the editor
            with ui.column().classes("flex-1 min-w-0 h-full"):
                ui.label("Adapter Help").classes("text-lg font-semibold mb-3 text-heading")

                # Dropdown to select adapter
                adapter_select = ui.select(options=[], label="Select an adapter for help", with_input=True).classes(
                    "w-full mb-3"
                )

                # Help text display area
                help_container = ui.column().classes("w-full flex-grow min-h-0")

                with help_container:
                    with ui.card().classes(
                        "bg-info-card border border-default w-full h-full overflow-y-auto shadow-sm p-4"
                    ):
                        help_text = ui.markdown(
                            "Select an adapter from the dropdown to see configuration examples."
                        ).classes("text-sm text-body-secondary")

                # Load adapters when dropdown is opened
                def load_adapters():
                    logger.info("Loading adapters for help interface")
                    try:
                        adapter_codes = get_all_adapter_codes()
                        if adapter_codes:
                            # Create options dict with adapter code as key and display name as value
                            adapter_select.options = {
                                adapter["code"]: f"{adapter['code']} - {adapter['name']}" for adapter in adapter_codes
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
                        adapter_info = next((a for a in adapter_codes if a["code"] == selected), None)

                        if not adapter_info:
                            logger.error(f"Adapter {selected} not found in adapter list")
                            help_text.set_content(f"Error: Adapter {selected} not found")
                            return

                        # Get the module path from the adapter class
                        adapter_class = adapter_info.get("class")
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
                        example_yaml_path = os.path.join(adapter_dir, "example.yaml")

                        logger.info(f"Looking for example.yaml at: {example_yaml_path}")

                        if os.path.exists(example_yaml_path):
                            # Read the actual example.yaml
                            with open(example_yaml_path) as f:
                                example_content = f.read()
                                # Load yaml to get the pretty-printed version
                                import yaml

                                yaml_content: dict[str, object] = yaml.safe_load(example_content)
                                # Remove OUTPUTS
                                _ = yaml_content.pop("OUTPUTS", None)
                                example_content = yaml.dump(yaml_content, indent=2)

                            help_md = f"""### {selected} Adapter Configuration

**Configuration Example from adapter:**

```yaml
{example_content}
```

**Note:** This is the official example from the `{selected}` adapter.
Adjust values like `instance_id`, `organisation`, etc. to match your setup.

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
        organisation: my_lab
        experiment_id: experiment_123
      requirements:
        interval: 1
```

**Tip:** Check the adapter documentation or repository for specific configuration requirements.
"""

                        _ = help_text.set_content(help_md + read_adapter_readme(adapter_dir))

                    except Exception as e:
                        logger.error(f"Error loading help for {selected}: {e}", exc_info=True)
                        help_text.set_content(f"""### Error Loading Adapter Help

Could not load configuration example for `{selected}`.

**Error:** {str(e)}

Check the logs for more details.
""")

                adapter_select.on("focus", load_adapters)
                adapter_select.on("update:model-value", show_adapter_help)

        # Save the editor to the configuration file, then restart the adapters
        def save_and_restart() -> None:
            abs_path = os.path.abspath(configuration_path)
            logger.info(f"Saving configuration to: {abs_path}")
            logger.debug(f"Configuration content length: {len(editor.value)} characters")

            # Log first 200 chars to see what's being saved
            preview = editor.value[:200].replace("\n", "\\n")
            logger.info(f"Configuration preview (first 200 chars): {preview}")

            try:
                with open(configuration_path, "w") as config_file:
                    _ = config_file.write(editor.value)
                logger.info(f"Configuration saved successfully to {abs_path}")

                # Verify what was actually written
                with open(configuration_path) as verify_file:
                    written_content = verify_file.read()
                logger.info(f"Verification: File now contains {len(written_content)} characters")
                logger.debug(f"Verification preview: {written_content[:200].replace(chr(10), '\\n')}")
                ui.notify(
                    f"Configuration saved to {os.path.basename(abs_path)}! Restarting...",
                    icon="check_circle",
                    color="positive",
                    timeout=2000,
                )
                # Give the notification time to display
                import time

                time.sleep(0.5)
                restart_leaf()
            except Exception as e:
                logger.error(f"Failed to save configuration: {e}", exc_info=True)
                ui.notify(f"Error saving configuration: {e}", icon="error", color="negative")

        # Save stays here because it saves this editor; restart and stop live in the header
        with ui.row().classes("w-full gap-4 py-4 border-t border-default bg-panel-light pl-4"):
            ui.button("Save & Restart", icon="save", on_click=save_and_restart).classes(
                "btn-primary px-6 py-3 rounded-lg transition-colors shadow-md"
            )
