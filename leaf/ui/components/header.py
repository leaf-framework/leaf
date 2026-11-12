"""LEAF UI header component."""

import base64
import os
from pathlib import Path

from nicegui import ui

from leaf.ui.components.app_control import create_app_controls
from leaf.ui.components.security_status import create_security_status
from leaf.ui.components.update_notice import create_update_notice


def create_header(dark_mode: ui.dark_mode, curr_dir: Path, drawer=None) -> None:
    """
    Create the LEAF application header with branding and dark mode toggle.

    Args:
        dark_mode: NiceGUI dark mode instance
        curr_dir: Current directory path for loading assets
        drawer: Optional left drawer to toggle via hamburger menu button
    """
    with ui.header().classes("leaf-header").style("padding: 16px; color: white;"):
        with ui.row().classes("justify-between items-center w-full"):
            with ui.row().classes("items-center"):
                if drawer is not None:
                    ui.button(icon="menu", on_click=drawer.toggle).props("flat round dense color=white").classes("mr-2")
                # Load SVG from images/icon.svg
                svg_path: Path = curr_dir / "images" / "icon.svg"
                if os.path.exists(svg_path):
                    with open(svg_path) as svg_file:
                        svg = svg_file.read()
                        b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
                        ui.html(f'<img width="32" height="32" src="data:image/svg+xml;base64,{b64}" />', sanitize=False)

                ui.label("LEAF").classes("text-3xl font-bold ml-2")
                # Renders the version label (click it to check for updates)
                # and the "update available" badge.
                create_update_notice()
                ui.label("Lightweight Equipment Adapter Framework").classes("text-sm opacity-80 ml-4 hidden md:block")

            with ui.row().classes("items-center"):
                create_security_status()

                create_app_controls()

                # Dark mode toggle with manual DOM class management
                def toggle_dark_mode():
                    if dark_mode.value:
                        dark_mode.disable()
                        toggle_button.icon = "light_mode"
                        toggle_button._props["title"] = "Switch to Dark Mode"
                        # Manually remove dark class via JavaScript
                        ui.run_javascript('document.documentElement.classList.remove("dark"); updateDarkModeStyles();')
                    else:
                        dark_mode.enable()
                        toggle_button.icon = "dark_mode"
                        toggle_button._props["title"] = "Switch to Light Mode"
                        # Manually add dark class via JavaScript
                        ui.run_javascript('document.documentElement.classList.add("dark"); updateDarkModeStyles();')

                toggle_button = (
                    ui.button("", icon="light_mode", on_click=toggle_dark_mode)
                    .props('flat round title="Switch to Dark Mode"')
                    .classes(
                        "text-yellow-300 bg-transparent hover:bg-white/20 transition-all duration-300 transform hover:scale-110"
                    )
                )
