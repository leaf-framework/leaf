import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.polling_watcher import PollingWatcher
from leaf.register.metadata import MetadataManager


class _FlakyWatcher(PollingWatcher):
    """A PollingWatcher whose _fetch_data raises once, then succeeds --
    simulates a single transient hardware read glitch."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetch_calls = 0

    def _fetch_data(self):
        self.fetch_calls += 1
        if self.fetch_calls == 1:
            raise RuntimeError("simulated hardware glitch")
        return {"measurement": {"n": self.fetch_calls}, "start": None, "stop": None}


class TestPollingWatcherResilience(unittest.TestCase):
    def setUp(self):
        self.metadata_manager = MetadataManager()
        self.metadata_manager.add_instance_value("organisation", "org")
        self.metadata_manager.add_instance_value("department", "dept")
        self.metadata_manager.add_instance_value("instance_id", "inst")
        self.metadata_manager.add_equipment_value("adapter_id", "adapter")

    def test_poll_loop_survives_a_single_fetch_data_exception(self):
        """A transient exception in one poll cycle (e.g. a hardware read
        glitch) must not permanently kill the background polling thread.

        Without an ErrorHolder configured -- the common/default case for
        any adapter that doesn't explicitly wire one up, since it defaults
        to None throughout the constructor chain -- it currently does:
        _handle_exception re-raises when there's no error_holder, killing
        the daemon thread silently. The experiment then just stops
        reporting data with no crash, no retry, and no visible signal."""
        received = []
        watcher = _FlakyWatcher(
            interval=1,
            metadata_manager=self.metadata_manager,
            callbacks=[lambda term, data: received.append((term, data))],
        )

        watcher.start()
        time.sleep(3.5)
        thread_alive = watcher._thread.is_alive()
        watcher.stop()

        self.assertGreaterEqual(watcher.fetch_calls, 3, "polling stopped calling _fetch_data after the first exception")
        self.assertTrue(thread_alive, "polling thread died after a single _fetch_data exception")
        self.assertTrue(received, "no measurement was ever delivered after the first exception")


if __name__ == "__main__":
    unittest.main()
