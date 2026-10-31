from leaf.modules.output_modules.mqtt import MQTT
from leaf.registry.discovery import discover_output_modules


def test_discovered_mqtt_output_is_the_mqtt_class() -> None:
    """Loading mqtt.py from its path made a second MQTT class, so control: true always failed."""
    [(name, cls)] = discover_output_modules({"mqtt"})
    assert name == "mqtt"
    assert cls is MQTT
