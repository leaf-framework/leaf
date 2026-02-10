from typing import Any

from nicegui import ui

from leaf.modules.output_modules.output_module import OutputModule


def _store_to_tree_nodes(store: dict, parent_path: str = "") -> list[dict[str, Any]]:
    """Convert a TopicStore nested dict into NiceGUI tree node list."""
    nodes = []
    for key, value in store.items():
        if key == "_value":
            continue
        node_id = f"{parent_path}/{key}" if parent_path else key
        node: dict[str, Any] = {"id": node_id, "label": key}
        if isinstance(value, dict):
            if "_value" in value:
                node["value"] = str(value["_value"])
            children = _store_to_tree_nodes(value, node_id)
            if children:
                node["children"] = children
        nodes.append(node)
    return nodes


def create_monitoring_tab(monitor_tab: ui.tab) -> None:
    with ui.tab_panel(monitor_tab):
        ui.label("Topic Store").classes("text-h6")

        with ui.row():
            ui.button("Expand", on_click=lambda: tree.expand())
            ui.button("Collapse", on_click=lambda: tree.collapse())

        def toggle_node(e) -> None:
            node_id = e.value
            expanded = tree._props.get("expanded", [])
            if node_id in expanded:
                expanded.remove(node_id)
            else:
                expanded.append(node_id)
            tree._props["expanded"] = expanded
            tree.update()

        tree = ui.tree([], label_key="label", on_select=toggle_node)

        tree.add_slot(
            "default-header",
            """
            <span :props="props"><strong>{{ props.node.label }}</strong></span>
        """,
        )
        tree.add_slot(
            "default-body",
            """
            <span :props="props" v-if="props.node.value">{{ props.node.value }}</span>
        """,
        )

        def refresh_tree() -> None:
            store_data = OutputModule.get_global_topic_store().get_all()
            tree._props["nodes"] = _store_to_tree_nodes(store_data)
            tree.update()

        ui.timer(2.0, refresh_tree)
