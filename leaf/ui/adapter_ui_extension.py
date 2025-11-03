"""Protocol for adapter UI extensions in LEAF.

Adapters can optionally provide UI extensions by implementing the get_ui_extension
static method that returns a dictionary with the tab configuration.
"""

from typing import Any, Callable, Dict, Optional, Protocol, TypedDict


class UIExtensionConfig(TypedDict):
    """Configuration for an adapter's UI extension.

    Attributes:
        tab_name: Display name for the tab
        tab_icon: Material icon name for the tab
        create_panel: Function that creates the UI panel (receives tab object)
        order: Optional ordering hint (lower numbers appear first, default: 1000)
    """
    tab_name: str
    tab_icon: str
    create_panel: Callable[[Any], None]
    order: Optional[int]


class AdapterUIExtension(Protocol):
    """Protocol that adapters can implement to provide UI extensions."""

    @staticmethod
    def get_ui_extension() -> UIExtensionConfig:
        """
        Return the UI extension configuration for this adapter.

        Returns:
            Dictionary containing:
                - tab_name: Name displayed on the tab
                - tab_icon: Material icon name (e.g., 'science', 'biotech', 'analytics')
                - create_panel: Function that creates the UI panel content
                - order: Optional tab ordering (lower = earlier, default 1000)

        Example:
            ```python
            @staticmethod
            def get_ui_extension():
                return {
                    'tab_name': 'My Adapter',
                    'tab_icon': 'science',
                    'create_panel': create_my_adapter_panel,
                    'order': 100
                }

            def create_my_adapter_panel(tab):
                with ui.tab_panel(tab):
                    ui.label('My adapter UI')
                    # ... custom UI components ...
            ```
        """
        ...


def has_ui_extension(adapter_class: type) -> bool:
    """
    Check if an adapter class has a UI extension.

    Args:
        adapter_class: The adapter class to check

    Returns:
        True if the adapter has a get_ui_extension method
    """
    return (
        hasattr(adapter_class, 'get_ui_extension') and
        callable(getattr(adapter_class, 'get_ui_extension'))
    )


def get_ui_extension(adapter_class: type) -> Optional[UIExtensionConfig]:
    """
    Get the UI extension configuration from an adapter class.

    Args:
        adapter_class: The adapter class

    Returns:
        UI extension configuration dict, or None if not available
    """
    if has_ui_extension(adapter_class):
        try:
            config = adapter_class.get_ui_extension()
            # Set default order if not specified
            if 'order' not in config:
                config['order'] = 1000
            return config
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Error getting UI extension from {adapter_class.__name__}: {e}"
            )
    return None
