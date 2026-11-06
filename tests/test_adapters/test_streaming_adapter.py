import os
import sys
import time
import unittest
import uuid
from threading import Thread
from unittest.mock import patch

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.adapters.core_adapters import streaming_adapter as streaming_adapter_module
from leaf.adapters.core_adapters.streaming_adapter import StreamingAdapter
from leaf.adapters.equipment_adapter import AbstractInterpreter
from leaf.error_handler.exceptions import AdapterBuildError
from leaf.modules.input_modules.event_watcher import EventWatcher
from leaf.modules.output_modules.output_module import OutputModule
from leaf.register.metadata import MetadataManager


class NoOpWatcher(EventWatcher):
    """Minimal watcher used only to satisfy StreamingAdapter's start/stop lifecycle.

    Tests drive it directly via _dispatch_callback to simulate a real
    watcher (e.g. FileWatcher.on_created) detecting a run and its filename.
    """

    def start(self) -> None:
        super().start()


class InMemoryOutput(OutputModule):
    """Minimal in-memory OutputModule so tests don't depend on a real broker."""

    def __init__(self):
        super().__init__()
        self.messages: dict[str, list] = {}
        self._connected = True

    def transmit(self, topic, data) -> None:
        self.messages.setdefault(topic, []).append(data)

    def pop(self, key=None):
        return None

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected


class StreamingInterpreter(AbstractInterpreter):
    def __init__(self, values):
        super().__init__()
        self.id = "TestStreamingAdapter"
        self._values = values
        self.filenames_seen = []

    def metadata(self, data):
        return data

    def measurement(self, data):
        return super().measurement(data)

    def stream(self, filename):
        self.filenames_seen.append(filename)
        yield from self._values


class NonStreamingInterpreter(AbstractInterpreter):
    def __init__(self):
        super().__init__()
        self.id = "TestNonStreaming"

    def metadata(self, data):
        return data

    def measurement(self, data):
        return super().measurement(data)


class CountingStreamInterpreter(AbstractInterpreter):
    """A stream() that ends after one item every call, so each restart is observable."""

    def __init__(self):
        super().__init__()
        self.id = "TestRestart"
        self.call_counts: dict[str, int] = {}

    def metadata(self, data):
        return data

    def measurement(self, data):
        return super().measurement(data)

    def stream(self, filename):
        self.call_counts[filename] = self.call_counts.get(filename, 0) + 1
        yield self.call_counts[filename]


class BlockingStreamInterpreter(AbstractInterpreter):
    """A stream() that blocks until released, to test concurrent filenames."""

    def __init__(self):
        super().__init__()
        self.id = "TestBlocking"
        import threading

        self.entered: dict[str, threading.Event] = {}
        self.release: dict[str, threading.Event] = {}

    def metadata(self, data):
        return data

    def measurement(self, data):
        return super().measurement(data)

    def stream(self, filename):
        import threading

        entered = self.entered.setdefault(filename, threading.Event())
        release = self.release.setdefault(filename, threading.Event())
        entered.set()
        release.wait(timeout=5)
        yield filename


class TestStreamingAdapter(unittest.TestCase):
    def setUp(self) -> None:
        unique_id = str(uuid.uuid4())
        self.instance_data = {
            "root": f"ROOT_TestStreamingAdapter_{unique_id}",
            "instance_id": unique_id,
            "organisation": f"TestStreamingAdapter_{unique_id}_ins",
            "department": f"TestStreamingAdapter_{unique_id}_dep",
        }
        self.metadata_manager = MetadataManager()
        self.metadata_manager.add_instance_data(self.instance_data)
        self.metadata_manager.add_equipment_value("adapter_id", f"TestStreamingAdapter_{unique_id}_equipment")
        self.output = InMemoryOutput()

    def test_requires_stream_method(self) -> None:
        with self.assertRaises(AdapterBuildError):
            StreamingAdapter(
                self.instance_data,
                NoOpWatcher(),
                self.output,
                NonStreamingInterpreter(),
                metadata_manager=self.metadata_manager,
            )

    def test_stream_launched_from_watcher_start_event(self) -> None:
        interpreter = StreamingInterpreter(range(1, 6))
        watcher = NoOpWatcher()
        with patch.object(streaming_adapter_module, "FIRST_RESTART_DELAY", 5):
            adapter = StreamingAdapter(
                self.instance_data,
                watcher,
                self.output,
                interpreter,
                maximum_message_size=5,
                metadata_manager=self.metadata_manager,
            )

            mthread = Thread(target=adapter.start)
            mthread.start()
            self._wait_for_running(adapter)

            # Simulate a real watcher (e.g. FileWatcher.on_created with
            # return_data=False) detecting a new run and its filename.
            watcher._dispatch_callback(self.metadata_manager.start, "measurements.csv")

            measurement_topic = self.metadata_manager.measurement(experiment_id=interpreter.id, measurement="unknown")
            self._wait_for(lambda: measurement_topic in self.output.messages)

            stream_thread = adapter._streams["measurements.csv"].thread

            adapter.stop()
            mthread.join(timeout=5)
            stream_thread.join(timeout=5)

            self.assertFalse(stream_thread.is_alive())
            self.assertEqual(adapter._streams, {})
            self.assertEqual(self.output.messages[measurement_topic], [[1, 2, 3, 4, 5]])
            self.assertEqual(interpreter.filenames_seen, ["measurements.csv"])

    def test_stream_not_launched_without_start_event(self) -> None:
        interpreter = StreamingInterpreter(range(1, 6))
        adapter = StreamingAdapter(
            self.instance_data,
            NoOpWatcher(),
            self.output,
            interpreter,
            metadata_manager=self.metadata_manager,
        )

        mthread = Thread(target=adapter.start)
        mthread.start()
        self._wait_for_running(adapter)
        time.sleep(0.2)

        self.assertEqual(adapter._streams, {})
        self.assertEqual(interpreter.filenames_seen, [])

        adapter.stop()
        mthread.join(timeout=5)

    def test_same_filename_start_event_restarts_stream(self) -> None:
        interpreter = StreamingInterpreter(range(1, 3))
        watcher = NoOpWatcher()
        with patch.object(streaming_adapter_module, "FIRST_RESTART_DELAY", 5):
            adapter = StreamingAdapter(
                self.instance_data,
                watcher,
                self.output,
                interpreter,
                maximum_message_size=2,
                metadata_manager=self.metadata_manager,
            )

            mthread = Thread(target=adapter.start)
            mthread.start()
            self._wait_for_running(adapter)

            watcher._dispatch_callback(self.metadata_manager.start, "same.csv")
            self._wait_for(lambda: len(interpreter.filenames_seen) >= 1)
            first_thread = adapter._streams["same.csv"].thread

            # A second start event for the SAME filename should replace it
            # with a fresh generation, not run alongside the old one.
            watcher._dispatch_callback(self.metadata_manager.start, "same.csv")
            self._wait_for(lambda: len(interpreter.filenames_seen) >= 2)

            self.assertFalse(first_thread.is_alive())
            self.assertEqual(len(adapter._streams), 1)
            self.assertEqual(interpreter.filenames_seen, ["same.csv", "same.csv"])

            adapter.stop()
            mthread.join(timeout=5)

    def test_different_filenames_stream_concurrently(self) -> None:
        interpreter = BlockingStreamInterpreter()
        watcher = NoOpWatcher()
        with patch.object(streaming_adapter_module, "FIRST_RESTART_DELAY", 5):
            adapter = StreamingAdapter(
                self.instance_data,
                watcher,
                self.output,
                interpreter,
                metadata_manager=self.metadata_manager,
            )

            mthread = Thread(target=adapter.start)
            mthread.start()
            self._wait_for_running(adapter)

            watcher._dispatch_callback(self.metadata_manager.start, "first.csv")
            watcher._dispatch_callback(self.metadata_manager.start, "second.csv")

            # Both should be blocked *inside* stream() concurrently - neither
            # is superseded/dropped by the other starting.
            self._wait_for(lambda: "first.csv" in interpreter.entered and interpreter.entered["first.csv"].is_set())
            self._wait_for(lambda: "second.csv" in interpreter.entered and interpreter.entered["second.csv"].is_set())
            self.assertEqual(set(adapter._streams.keys()), {"first.csv", "second.csv"})
            self.assertTrue(adapter._streams["first.csv"].thread.is_alive())
            self.assertTrue(adapter._streams["second.csv"].thread.is_alive())

            interpreter.release["first.csv"].set()
            interpreter.release["second.csv"].set()

            adapter.stop()
            mthread.join(timeout=5)
            self.assertEqual(adapter._streams, {})

    def test_stream_restarts_after_completion(self) -> None:
        interpreter = CountingStreamInterpreter()
        watcher = NoOpWatcher()
        with patch.object(streaming_adapter_module, "FIRST_RESTART_DELAY", 0.05):
            adapter = StreamingAdapter(
                self.instance_data,
                watcher,
                self.output,
                interpreter,
                maximum_message_size=1,
                metadata_manager=self.metadata_manager,
            )

            mthread = Thread(target=adapter.start)
            mthread.start()
            self._wait_for_running(adapter)

            watcher._dispatch_callback(self.metadata_manager.start, "measurements.csv")
            self._wait_for(lambda: interpreter.call_counts.get("measurements.csv", 0) >= 3)

            stream_thread = adapter._streams["measurements.csv"].thread

            adapter.stop()
            mthread.join(timeout=5)
            stream_thread.join(timeout=5)

            self.assertFalse(stream_thread.is_alive())
            self.assertGreaterEqual(interpreter.call_counts["measurements.csv"], 3)

    def _wait_for_running(self, adapter, timeout: float = 10.0) -> None:
        self._wait_for(adapter.is_running, timeout)
        self.assertTrue(adapter.is_running())

    def _wait_for(self, predicate, timeout: float = 5.0) -> None:
        waited = 0.0
        step = 0.05
        while not predicate() and waited < timeout:
            time.sleep(step)
            waited += step


if __name__ == "__main__":
    unittest.main()
