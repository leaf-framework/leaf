"""The adapters LEAF is running, shared by leaf.start and the UI without an import cycle."""

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from leaf.adapters.equipment_adapter import EquipmentAdapter

# Only appended to and cleared, never reassigned, so every importer sees the same list
adapters: list["EquipmentAdapter"] = []

# Set once LEAF has tried to start every configured instance; until then the list can still grow
startup_done = threading.Event()
