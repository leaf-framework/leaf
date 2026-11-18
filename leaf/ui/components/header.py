"""LEAF sidebar rail and phone bar, laid out like leaf-portal's."""

from nicegui import ui

from leaf.ui.components.app_control import create_app_controls
from leaf.ui.components.security_status import create_security_status
from leaf.ui.components.update_notice import create_update_notice

# None follows the OS; the button cycles to an override.
_NEXT_THEME = {None: True, True: False, False: None}
_THEME_ICON = {
    None: "sym_r_brightness_auto",
    True: "sym_r_dark_mode",
    False: "sym_r_light_mode",
}


def _logo(icon_src: str) -> None:
    _ = ui.html(f'<img width="32" height="32" src="{icon_src}" alt="" />', sanitize=False)


def create_rail(icon_src: str) -> ui.left_drawer:
    """The canopy rail; open the returned drawer to add the page tabs under the mark."""
    drawer = ui.left_drawer(value=False).props("show-if-above breakpoint=1024 width=248").classes("leaf-rail p-0 gap-0")
    with drawer:
        with ui.element("div").classes("leaf-mark"):
            _logo(icon_src)
            _ = ui.label("LEAF")
    return drawer


def create_rail_footer(dark: ui.dark_mode) -> None:
    """Status, restart/stop and theme at the foot of the rail, then the version."""
    with ui.element("div").classes("leaf-me"):
        create_security_status()
        create_app_controls()

        def next_theme() -> None:
            dark.value = _NEXT_THEME[dark.value]
            _ = theme_button.props(f"icon={_THEME_ICON[dark.value]}")

        theme_button = (
            ui.button(icon=_THEME_ICON[dark.value], on_click=next_theme, color=None)
            .props("flat round dense")
            .tooltip("Theme: follow system, dark or light")
        )
    # Small and last: the thing to quote in a bug report.
    with ui.element("div").classes("leaf-build"):
        create_update_notice()


def create_mobile_bar(drawer: ui.left_drawer, icon_src: str) -> None:
    """Phones only: the rail slides in from this bar's menu button."""
    with ui.header().classes("leaf-mobile-bar lg:hidden items-center gap-3 px-4 py-2"):
        _ = ui.button(icon="menu", on_click=drawer.toggle).props("flat round dense color=white")
        _logo(icon_src)
        _ = ui.label("LEAF").classes("text-lg font-semibold tracking-wide")
