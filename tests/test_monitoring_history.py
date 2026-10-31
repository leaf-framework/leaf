import time
from typing import cast

from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.modules.output_modules.topic_store import HISTORY_LENGTH, TopicStore
from leaf.modules.phase_modules.measure import MeasurePhase, point_json_of
from leaf.register.metadata import MetadataManager
from leaf.ui.tabs.monitoring import chart_series, format_value, metric_name


class FakeLeafPoint:
    """Stands in for leafobject.LeafPoint, which LEAF recognises by to_json()."""

    def __init__(self, metric: str = "T", value: float = 298.0) -> None:
        self.metric: str = metric
        self.value: float = value

    def to_json(self) -> dict[str, object]:
        return {"measurement": "m", "tags": {"metric": self.metric}, "fields": {"value": self.value}, "timestamp": 10.0}


class PointInterpreter:
    """Interpreter whose measurement() returns whatever the test gives it."""

    def __init__(self, result: object) -> None:
        self.id: str = "exp"
        self.result: object = result

    def measurement(self, _data: object) -> object:
        return self.result


def measure(result: object) -> list[tuple[str, object]]:
    """Run MeasurePhase.update with an interpreter returning `result`."""
    metadata = MetadataManager()
    metadata.add_equipment_value("adapter_id", "test_points")
    for key in ("organisation", "department", "instance_id"):
        metadata.add_instance_value(key, "test_points")
    phase = MeasurePhase(metadata_manager=metadata)
    # Only id and measurement() are used, so a stand-in is enough
    phase.set_interpreter(cast(AbstractInterpreter, cast(object, PointInterpreter(result))))
    return phase.update("raw", experiment_id="exp", measurement="m") or []


def test_measure_publishes_a_leafpoint_under_its_metric() -> None:
    [(topic, payload)] = measure(FakeLeafPoint("pH", 6.5))
    assert topic.endswith("/pH")
    assert payload == FakeLeafPoint("pH", 6.5).to_json()


def test_measure_splits_a_list_of_leafpoints_per_metric() -> None:
    messages = dict(measure([FakeLeafPoint("T", 298.0), FakeLeafPoint("pH", 6.5)]))
    assert sorted(topic.rsplit("/", 1)[-1] for topic in messages) == ["T", "pH"]
    assert all(isinstance(points, list) and isinstance(points[0], dict) for points in messages.values())


def test_point_json_accepts_any_point_with_to_json() -> None:
    assert point_json_of(FakeLeafPoint()) == FakeLeafPoint().to_json()
    assert point_json_of({"fields": {}}) is None
    assert point_json_of("text") is None


def test_history_keeps_numeric_values_per_topic() -> None:
    store = TopicStore()
    store.set("mqtt/a/T", [FakeLeafPoint().to_json()])
    store.set("mqtt/a/T", {"fields": {"value": 299}, "timestamp": 11.0})
    store.set("mqtt/a/phase", {"fields": {"value": "GROWTH"}})
    store.set("mqtt/a/raw", "not a point")
    assert store.get_history() == {"mqtt/a/T": [(10.0, 298.0), (11.0, 299.0)]}


def test_history_is_bounded() -> None:
    store = TopicStore()
    for i in range(HISTORY_LENGTH + 5):
        store.set("mqtt/a/T", {"fields": {"value": i}, "timestamp": float(i)})
    history = store.get_history()["mqtt/a/T"]
    assert len(history) == HISTORY_LENGTH
    assert history[0] == (5.0, 5.0)


def testchart_series_uses_milliseconds_and_drops_module_name() -> None:
    series = chart_series({"mqtt/a/T": [(10.0, 298.0)]}, ["mqtt/a/T"])
    assert series == [
        {"name": "a/T", "type": "line", "showSymbol": False, "color": "#5470c6", "data": [[10000.0, 298.0]]}
    ]


def test_metric_color_does_not_depend_on_selection() -> None:
    history = {"mqtt/a/T": [(1.0, 1.0)], "mqtt/a/pH": [(1.0, 1.0)], "mqtt/a/F": [(1.0, 1.0)]}
    alone = chart_series(history, ["mqtt/a/pH"])[0]["color"]
    together = chart_series(history, ["mqtt/a/F", "mqtt/a/T", "mqtt/a/pH"])[2]["color"]
    assert alone == together


def test_tile_name_and_value() -> None:
    assert metric_name("mqtt/demo/reactor1/T") == "T"
    assert format_value(298.8987080958116) == "298.899"


def test_history_uses_now_when_a_point_has_no_timestamp() -> None:
    store = TopicStore()
    before = time.time()
    store.set("mqtt/a/T", {"fields": {"value": 1}})
    [(timestamp, value)] = store.get_history()["mqtt/a/T"]
    assert timestamp >= before
    assert value == 1.0


def test_chart_grows_one_legend_row_per_series() -> None:
    from leaf.ui.tabs.monitoring import LEGEND_ROW_HEIGHT, chart_layout

    one, three = chart_layout(1), chart_layout(3)
    assert cast(int, three["height"]) - cast(int, one["height"]) == 2 * LEGEND_ROW_HEIGHT
