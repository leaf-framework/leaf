from typing import Any, cast

from nicegui import ui

from leaf.modules.output_modules.output_module import OutputModule
from leaf.modules.output_modules.topic_store import ENTITY_SEPARATOR


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


def metric_name(key: str) -> str:
    """Last topic segment of a history key, e.g. "T" for ".../reactor1/T#well A1"."""
    topic = key.split(ENTITY_SEPARATOR, 1)[0]
    return topic.rsplit("/", 1)[-1]


def format_value(value: float) -> str:
    """6 significant digits, as in the chart tooltip."""
    return f"{value:.6g}"


def full_label(key: str) -> str:
    """History key without the output module name it is stored under."""
    return key.split("/", 1)[-1]


def instance_name(key: str) -> str:
    """Instance ID of a measurement topic, which ends in <instance_id>/experiment/<experiment_id>/measurement/<metric>; else ""."""
    parts = key.partition(ENTITY_SEPARATOR)[0].split("/")
    if len(parts) < 5 or parts[-2] != "measurement" or parts[-4] != "experiment":
        return ""
    return parts[-5]


def series_label(key: str, all_keys: list[str]) -> str:
    """ "<instance_id> · <entity> · <metric>" for a measurement topic, else the full label.

    The entity only shows when several entities share the topic (e.g. wells of a plate); a single
    entity per topic usually just names the instance again (leaf-example tags every point "bioreactor 1").
    """
    topic, _, entity = key.partition(ENTITY_SEPARATOR)
    instance = instance_name(key)
    if not instance:
        return full_label(key)
    # Instance stays in: entity names repeat across instances
    names = [instance]
    shared = [other for other in all_keys if other.partition(ENTITY_SEPARATOR)[0] == topic]
    if entity and len(shared) > 1:
        names.append(entity)
    names.append(metric_name(topic))
    return " · ".join(names)


def tile_label(key: str, all_keys: list[str]) -> str:
    """Series label without the instance, which the tile's group box already names."""
    instance = instance_name(key)
    label = series_label(key, all_keys)
    if instance:
        return label.removeprefix(f"{instance} · ")
    return label


# ECharts' default palette, assigned per metric rather than per selected line
PALETTE = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc"]


def metric_color(topic: str, all_topics: list[str]) -> str:
    """Colour from the metric's place among all known metrics, so it does not change with the selection."""
    return PALETTE[sorted(all_topics).index(topic) % len(PALETTE)]


def chart_series(history: dict[str, list[tuple[float, float]]], topics: list[str]) -> list[dict[str, object]]:
    """ECharts line series for the chosen topics, timestamps in milliseconds."""
    series: list[dict[str, object]] = []
    for topic in topics:
        points = [[timestamp * 1000, value] for timestamp, value in history.get(topic, [])]
        series.append(
            {
                "name": series_label(topic, list(history)),
                "type": "line",
                "showSymbol": False,
                "color": metric_color(topic, list(history)),
                "data": points,
            }
        )
    return series


# Pixel layout of the chart: plot area, then the zoom slider, then one legend row per series
PLOT_HEIGHT = 320
SLIDER_HEIGHT = 30
LEGEND_ROW_HEIGHT = 22


def chart_layout(series_count: int) -> dict[str, object]:
    """Grid, slider and vertical legend below the plot, leaving room for every series' legend row."""
    legend_height = series_count * LEGEND_ROW_HEIGHT
    slider_bottom = legend_height + 16
    return {
        "legend": {"orient": "vertical", "left": 40, "bottom": 8},
        # Use the full width: ECharts reserves 10% per side by default
        "grid": {"left": 8, "right": 24, "top": 16, "bottom": slider_bottom + SLIDER_HEIGHT + 8, "containLabel": True},
        "dataZoom": [
            {"type": "inside"},
            {"type": "slider", "left": 40, "right": 24, "bottom": slider_bottom, "height": SLIDER_HEIGHT},
        ],
        "height": 16 + PLOT_HEIGHT + SLIDER_HEIGHT + 32 + legend_height,
    }


def create_monitoring_tab(monitor_tab: ui.tab) -> None:
    with ui.tab_panel(monitor_tab):
        # Plot and tree as sub-tabs, so the growing chart does not push the tree out of view
        with ui.tabs().classes("w-full") as views:
            plot_view = ui.tab("Plot", icon="show_chart")
            tree_view = ui.tab("Topic tree", icon="account_tree")
        with ui.tab_panels(views, value=plot_view).classes("w-full"):
            with ui.tab_panel(plot_view):
                # Latest value per series, boxed per instance; the full topic is in the tooltip
                tiles = ui.row().classes("w-full gap-3")
                tile_groups: dict[str, ui.row] = {}
                tile_values: dict[str, ui.label] = {}

                # Metrics with different scales do not share an axis well, so the user picks which to plot
                with ui.row().classes("w-full items-center no-wrap"):
                    metric_select = ui.select(options={}, multiple=True, label="Metrics to plot").classes("grow")
                    _ = metric_select.props("use-chips")
                    _ = ui.button(
                        "Add all",
                        icon="done_all",
                        on_click=lambda: metric_select.set_value(
                            sorted(OutputModule.get_global_topic_store().get_history())
                        ),
                    ).props("flat")
                    _ = ui.button("Clear all", icon="clear_all", on_click=lambda: metric_select.set_value([])).props(
                        "flat"
                    )
                # The first metric is picked for the user once; after "Clear all" the plot stays empty
                picked_default = False
                layout = chart_layout(0)
                chart = ui.echart(
                    {
                        # Axis trigger lists every plotted line at the hovered time; 6 significant digits keeps it readable
                        "tooltip": {
                            "trigger": "axis",
                            ":valueFormatter": "(v) => { if (v === null || v === undefined) { return '-'; } return String(Number(v.toPrecision(6))); }",
                        },
                        "legend": layout["legend"],
                        "grid": layout["grid"],
                        "xAxis": {"type": "time"},
                        "yAxis": {"type": "value", "scale": True},
                        "dataZoom": layout["dataZoom"],
                        "series": [],
                    }
                ).classes("w-full")
                _ = chart.style(f"height: {layout['height']}px")

                def refresh_chart() -> None:
                    nonlocal picked_default
                    history = OutputModule.get_global_topic_store().get_history()
                    topics = sorted(history)
                    for topic in topics:
                        if topic not in tile_values:
                            instance = instance_name(topic)
                            if instance not in tile_groups:
                                with tiles, ui.card().props("flat bordered").classes("p-3 gap-2"):
                                    _ = ui.label(instance or "Other").classes("text-sm font-medium")
                                    tile_groups[instance] = ui.row().classes("gap-3")
                            stripe = f"border-left: 4px solid {metric_color(topic, topics)}"
                            with (
                                tile_groups[instance],
                                ui.card().classes("p-3 min-w-32").style(stripe).tooltip(full_label(topic)),
                            ):
                                _ = ui.label(tile_label(topic, topics)).classes("text-xs text-body-secondary")
                                tile_values[topic] = ui.label().classes("text-2xl font-bold text-heading")
                        _ = tile_values[topic].set_text(format_value(history[topic][-1][1]))
                    # NiceGUI leaves the options type unparametrised
                    _ = metric_select.set_options({topic: series_label(topic, topics) for topic in topics})  # pyright: ignore[reportUnknownMemberType]
                    selected = cast(list[str], metric_select.value or [])
                    if not selected and topics and not picked_default:
                        selected = [topics[0]]
                        _ = metric_select.set_value(selected)
                        picked_default = True
                    layout = chart_layout(len(selected))
                    chart.options.update(  # pyright: ignore[reportUnknownMemberType]
                        {
                            "legend": layout["legend"],
                            "grid": layout["grid"],
                            "dataZoom": layout["dataZoom"],
                            "series": chart_series(history, selected),
                        }
                    )
                    _ = chart.style(f"height: {layout['height']}px")
                    chart.update()

                _ = ui.timer(2.0, refresh_chart)

            with ui.tab_panel(tree_view):
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
