"""LEAF Documentation tab."""

from nicegui import ui

from leaf.registry.discovery import get_all_adapter_codes


def create_documentation_tab(docs_tab: ui.tab, docs_main_md: str, docs_protips_md: str) -> None:
    """
    Create the documentation tab panel.

    Args:
        docs_tab: The tab component this panel belongs to
        docs_main_md: Main documentation markdown content
        docs_protips_md: Pro tips markdown content
    """
    with ui.tab_panel(docs_tab).classes('w-full p-6'):
        with ui.card().classes('leaf-card w-full'):
            with ui.card_section():
                with ui.row().classes('items-center mb-6'):
                    ui.icon('help', size='2rem').classes('text-icon')
                    ui.label('LEAF Documentation').classes('text-2xl font-bold text-heading ml-2')

                with ui.row().classes('w-full gap-6'):
                    # Main documentation - Left side (50%)
                    with ui.column().classes('w-45/100'):
                        ui.markdown(docs_main_md).classes('prose max-w-none text-sm')

                    # Quick reference sidebar - Right side (50%)
                    with ui.column().classes('w-45/100 gap-4'):
                        with ui.card().classes('bg-info-card border border-default w-full'):
                            with ui.card_section().classes('w-full'):
                                ui.label('Quick Links').classes('text-lg font-bold text-heading mb-3')
                                with ui.column().classes('gap-2'):
                                    ui.button('Official Documentation',
                                            on_click=lambda: ui.run_javascript('window.open("https://leaf.systemsbiology.nl", "_blank")')).classes(
                                        'btn-secondary w-full rounded transition-colors'
                                    )
                                    ui.button('Adapter Templates',
                                            on_click=lambda: ui.run_javascript('window.open("https://gitlab.com/LabEquipmentAdapterFramework/leaf-adapters/leaf-template", "_blank")')).classes(
                                        'btn-secondary w-full rounded transition-colors'
                                    )
                                    ui.button('Report Issues / Request Features',
                                            on_click=lambda: ui.run_javascript('window.open("https://gitlab.com/LabEquipmentAdapterFramework/leaf/-/issues", "_blank")')).classes(
                                        'btn-secondary w-full rounded transition-colors'
                                    )

                        with ui.card().classes('bg-info-card border border-default w-full'):
                            with ui.card_section().classes('w-full'):
                                ui.label('System Status').classes('text-lg font-bold text-heading mb-3')
                                with ui.column().classes('gap-2'):
                                    with ui.row().classes('items-center justify-between'):
                                        ui.label('Framework').classes('text-sm font-medium')
                                        ui.chip('ACTIVE', color='grey')
                                    with ui.row().classes('items-center justify-between'):
                                        ui.label('Configuration').classes('text-sm font-medium')
                                        ui.chip('LOADED', color='grey')
                                    with ui.row().classes('items-center justify-between'):
                                        ui.label('Adapters').classes('text-sm font-medium')
                                        installed_count = len(get_all_adapter_codes())
                                        ui.chip(f'{installed_count} INSTALLED', color='grey')

                        with ui.card().classes('bg-info-card border border-default w-full'):
                            with ui.card_section().classes('w-full'):
                                ui.label('Pro Tips').classes('text-lg font-bold text-heading mb-3')
                                ui.markdown(docs_protips_md).classes('text-sm text-body-secondary')
