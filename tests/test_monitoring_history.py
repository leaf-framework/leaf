import time
from typing import cast

import pytest

from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.modules.output_modules.topic_store import HISTORY_LENGTH, TopicStore
from leaf.modules.phase_modules.measure import MeasurePhase, point_json_of
from leaf.register.metadata import MetadataManager
from leaf.ui.tabs.monitoring import chart_series, format_value, metric_name, series_label


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


def measure(
    result: object, organisation: str = "test_points", department: str = "test_points"
) -> list[tuple[str, object]]:
    """Run MeasurePhase.update with an interpreter returning `result`."""
    metadata = MetadataManager()
    metadata.add_equipment_value("adapter_id", "test_points")
    metadata.add_instance_value("organisation", organisation)
    metadata.add_instance_value("department", department)
    metadata.add_instance_value("instance_id", "test_points")
    phase = MeasurePhase(metadata_manager=metadata)
    # Only id and measurement() are used, so a stand-in is enough
    phase.set_interpreter(cast(AbstractInterpreter, cast(object, PointInterpreter(result))))
    return phase.update("raw", experiment_id="exp", measurement="m") or []


def test_measure_publishes_a_leafpoint_under_its_metric() -> None:
    [(topic, payload)] = measure(FakeLeafPoint("pH", 6.5))
    assert topic.endswith("/pH")
    expected = FakeLeafPoint("pH", 6.5).to_json()
    expected["tags"] = {
        "metric": "pH",
        "organisation": "test_points",
        "department": "test_points",
        "experiment_id": "exp",
        "entity": "test_points",
    }
    assert payload == expected


def test_measure_adds_instance_tags_but_keeps_the_adapters_own() -> None:
    [(_, payload)] = measure({"tags": {"metric": "T", "organisation": "lab"}, "fields": {"value": 1.0}})
    assert cast(dict[str, dict[str, str]], payload)["tags"] == {
        "metric": "T",
        "organisation": "lab",
        "department": "test_points",
        "experiment_id": "exp",
        "entity": "test_points",
    }


def test_a_differing_organisation_tag_is_kept_with_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    point = {"tags": {"metric": "T", "organisation": "lab"}, "fields": {"value": 1.0}}
    messages = measure([point, dict(point, tags=dict(point["tags"]))])
    points = [p for _, batch in messages for p in cast(list[dict[str, dict[str, str]]], batch)]
    assert [p["tags"]["organisation"] for p in points] == ["lab", "lab"]
    warnings = [r for r in caplog.records if "differs from the configured organisation" in r.getMessage()]
    assert len(warnings) == 1


def test_each_instance_tags_its_points_with_its_own_organisation_and_department() -> None:
    [(reactor_topic, reactor)] = measure(FakeLeafPoint(), organisation="wur", department="ssb")
    [(sensor_topic, sensor)] = measure(FakeLeafPoint(), organisation="wur", department="microbiology")
    assert cast(dict[str, dict[str, str]], reactor)["tags"]["department"] == "ssb"
    assert cast(dict[str, dict[str, str]], sensor)["tags"]["department"] == "microbiology"
    # The tags match the instance's own topic
    assert reactor_topic.startswith("wur/ssb/")
    assert sensor_topic.startswith("wur/microbiology/")


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


def test_measure_always_puts_the_entity_between_measurement_and_metric() -> None:
    reactors = [
        {"tags": {"metric": "volume", "entity": "reactor_1"}, "fields": {"value": 1.0}},
        {"tags": {"metric": "volume", "entity": "reactor/2"}, "fields": {"value": 2.0}},
        {"tags": {"metric": "volume", "entity": "test_points"}, "fields": {"value": 3.0}},
        {"tags": {"metric": "volume"}, "fields": {"value": 4.0}},
    ]
    messages = measure(reactors)
    instance = "test_points/test_points/test_points/test_points"
    assert [topic for topic, _ in messages] == [
        f"{instance}/measurement/reactor_1/volume",
        # A "/" in the entity would add a level
        f"{instance}/measurement/reactor_2/volume",
        # A point without an entity is about the instance itself
        f"{instance}/measurement/test_points/volume",
        f"{instance}/measurement/test_points/volume",
    ]


class InvalidLeafPoint:
    """A LeafPoint whose to_json() fails validation, as leafobject does without an entity tag."""

    def to_json(self) -> dict[str, object]:
        raise ValueError("Entity tag is not set")


def test_an_invalid_point_is_reported_and_only_it_is_dropped() -> None:
    from leaf.error_handler.error_holder import ErrorHolder

    metadata = MetadataManager()
    metadata.add_instance_value("instance_id", "i")
    holder = ErrorHolder()
    phase = MeasurePhase(metadata_manager=metadata, error_holder=holder)
    batch = [InvalidLeafPoint(), FakeLeafPoint("T")]
    phase.set_interpreter(cast(AbstractInterpreter, cast(object, PointInterpreter(batch))))
    messages = phase.update("raw") or []
    assert [topic.rsplit("/", 1)[-1] for topic, _ in messages] == ["T"]
    phase.set_interpreter(cast(AbstractInterpreter, cast(object, PointInterpreter(InvalidLeafPoint()))))
    assert phase.update("raw") == []
    errors = [str(error) for error, _ in holder.get_unseen_errors()]
    assert len(errors) == 2
    assert all("Entity tag is not set" in error for error in errors)


def test_an_unset_experiment_id_is_not_tagged() -> None:
    interpreter = PointInterpreter({"tags": {"metric": "T"}, "fields": {"value": 1.0}})
    interpreter.id = "undefined"
    metadata = MetadataManager()
    metadata.add_instance_value("instance_id", "i")
    phase = MeasurePhase(metadata_manager=metadata)
    phase.set_interpreter(cast(AbstractInterpreter, cast(object, interpreter)))
    [(_, payload)] = phase.update("raw") or []
    assert "experiment_id" not in cast(dict[str, dict[str, str]], payload)["tags"]


def test_series_label_names_instance_entity_and_metric() -> None:
    reactor = "mqtt/demo/wur/ssb/leaf_bpc/bpcgo1/measurement/reactor_1/volume"
    plain = "mqtt/leaf/org/dept/Example/reactor_a/measurement/reactor_a/pH"
    assert series_label(reactor) == "bpcgo1 · reactor_1 · volume"
    assert series_label(plain) == "reactor_a · pH"
    assert series_label("mqtt/a/T") == "a/T"
    assert metric_name(reactor) == "volume"


def test_tile_label_leaves_the_instance_to_its_group() -> None:
    from leaf.ui.tabs.monitoring import instance_name, tile_label

    reactor = "mqtt/demo/wur/ssb/leaf_bpc/bpcgo1/measurement/reactor_1/volume"
    plain = "mqtt/leaf/org/dept/Example/reactor_a/measurement/reactor_a/pH"
    assert instance_name(reactor) == "bpcgo1"
    assert tile_label(reactor) == "reactor_1 · volume"
    assert instance_name(plain) == "reactor_a"
    assert tile_label(plain) == "pH"
    assert instance_name("mqtt/a/T") == ""
    assert tile_label("mqtt/a/T") == "a/T"


def test_mqtt_transmit_feeds_the_plot_history() -> None:
    from unittest.mock import MagicMock, patch

    from leaf.modules.output_modules.mqtt import MQTT
    from leaf.modules.output_modules.output_module import OutputModule

    # A connected client whose publish succeeds
    client = MagicMock()
    client.configure_mock(**{"is_connected.return_value": True, "publish.return_value.rc": 0})
    with patch("paho.mqtt.client.Client", return_value=client):
        output: OutputModule = MQTT(broker="localhost", port=1883, clientid="plot_history")
        # transmit() takes an unparametrised dict
        assert output.transmit("plot/history/T", FakeLeafPoint().to_json())  # pyright: ignore[reportUnknownMemberType]
    # MQTT publishes JSON text, but the plot needs the points themselves
    assert OutputModule.get_global_topic_store().get_history()[f"{output.name}/plot/history/T"] == [(10.0, 298.0)]
