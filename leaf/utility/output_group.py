"""Several outputs that each receive all data, each with its own fallback and failure handling."""

from collections.abc import Callable, Iterator
from typing import Any

from leaf.modules.output_modules.output_module import OutputModule


# Lives outside output_modules/ so discovery does not offer it as a plugin.
class OutputGroup(OutputModule):
    def __init__(self, members: list[OutputModule]) -> None:
        super().__init__()
        self._members: list[OutputModule] = members

    def outputs(self) -> list[OutputModule]:
        return list(self._members)

    def transmit(self, topic: str, data: str | dict[Any, Any] | None = None) -> bool:
        # Every member gets the data, also when an earlier one failed; each falls back on its own.
        sent = True
        for member in self._members:
            if not member.transmit(topic, data):
                sent = False
        return sent

    def pop(self, key: str | None = None) -> Any:
        for member in self._members:
            message = member.pop(key)
            if message is not None:
                return message
        return None

    def pop_all_messages(self) -> Iterator[Any]:
        for member in self._members:
            yield from member.pop_all_messages()

    def connect(self) -> None:
        for member in self._members:
            member.connect()

    def disconnect(self) -> None:
        for member in self._members:
            member.disconnect()

    def is_connected(self) -> bool:
        return all(member.is_connected() for member in self._members)

    def flush(self, topic: str) -> None:
        for member in self._members:
            member.flush(topic)

    def subscribe(self, topic: str, callback: Callable[[str, str], None] | None = None) -> None:
        # Control messages can then arrive through any of the brokers
        for member in self._members:
            member.subscribe(topic, callback)

    def unsubscribe(self, topic: str) -> str | None:
        result = None
        for member in self._members:
            result = member.unsubscribe(topic)
        return result

    def enable(self) -> None:
        for member in self._members:
            member.enable()

    def disable(self) -> None:
        for member in self._members:
            member.disable()

    def is_enabled(self) -> bool:
        return all(member.is_enabled() for member in self._members)

    def security_warnings(self) -> list[str]:
        issues: list[str] = []
        for member in self._members:
            issues += member.security_warnings()
        return issues

    def on_adapter_ready(self, metadata_manager: Any) -> None:
        for member in self._members:
            member.on_adapter_ready(metadata_manager)

    def on_adapter_stop(self, metadata_manager: Any) -> None:
        for member in self._members:
            member.on_adapter_stop(metadata_manager)

    @property
    def name(self) -> str:
        names: list[str] = []
        for member in self._members:
            names.append(member.name)
        return " + ".join(names)
