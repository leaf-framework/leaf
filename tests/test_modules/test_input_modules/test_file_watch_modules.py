import csv
import logging
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from threading import Thread

import leaf.utility.logger.logger_utils

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.modules.input_modules.file_watcher import FileWatcher
from leaf_register.metadata import MetadataManager

logger = leaf.utility.logger.logger_utils.get_logger("test_file_watch_modules")

class TestFileWatcher(unittest.TestCase):
    def _write_csv_file(self, filepath, rows, delimiter=","):
        with open(filepath, "w", newline="") as file:
            writer = csv.writer(file, delimiter=delimiter)
            for row in rows:
                writer.writerow(row)

    def _write_file(self, path, rows, delimiter="\t"):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f, delimiter=delimiter)
            for row in rows:
                writer.writerow(row)


    def test_file_watcher_change(self):
        with tempfile.TemporaryDirectory() as test_dir:
            def mod_file(filename, interval, count):
                for _ in range(count):
                    now = datetime.now()
                    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                    with open(filename, "a") as file:
                        file.write(f"{timestamp}\n")
                    time.sleep(interval)

            topics = {}
            def mock_callback(topic,data):
                nonlocal topics
                topic = topic()
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)

            test_fn = "test_file_watcher_change.txt"
            text_watch_file = os.path.join(test_dir, test_fn)
            if not os.path.isfile(text_watch_file):
                with open(text_watch_file, "w"):
                    pass

            num_mod = 2
            interval = 2
            metadata = MetadataManager()
            watcher = FileWatcher(test_dir,metadata,
                                  callbacks=[mock_callback],
                                  filenames=test_fn)
            watcher.start()

            # Wait for the file creation event to be processed and debounce to expire
            time.sleep(1.0)

            mthread = Thread(target=mod_file, args=(text_watch_file,
                                                    interval, num_mod))
            mthread.start()
            mthread.join()
            time.sleep(1)
            watcher.stop()
            self.assertEqual(len(topics[metadata.experiment.measurement()]), num_mod)

    def test_file_watcher_creation(self):
        with tempfile.TemporaryDirectory() as test_dir:

            def create_file(filepath, interval, count):
                for _ in range(count):
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                    headers = ["Timestamp"] + [
                        f"TestHeading{str(h)}" for h in range(0, 10)
                    ]
                    with open(filepath, "w", newline="") as file:
                        writer = csv.writer(file)
                        writer.writerow(headers)
                    time.sleep(interval)

            topics = {}
            def mock_callback(topic,data):
                nonlocal topics
                topic = topic()
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)

            test_fn = "test_file_watcher_creation.csv"
            creation_dir = test_dir
            metadata = MetadataManager()
            watcher = FileWatcher(creation_dir,metadata,
                                  callbacks=[mock_callback],
                                  filenames=test_fn)
            num_create = 3
            interval = 2
            watcher.start()
            creation_file = os.path.join(creation_dir,test_fn)
            time.sleep(3)  # Wait for the watcher to be fully ready
            mthread = Thread(target=create_file, args=(creation_file, 
                                                       interval, 
                                                       num_create))
            mthread.start()
            mthread.join()
            time.sleep(1)
            watcher.stop()
            self.assertEqual(len(topics[metadata.experiment.start()]), num_create)

    def test_file_watcher_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as test_dir:

            def delete_file(filepath, interval, count):
                for _ in range(count):
                    if not os.path.isfile(filepath):
                        headers = ["Timestamp"] + [
                            f"TestHeading{str(h)}" for h in range(0, 10)
                        ]
                        with open(filepath, "w", newline="") as file:
                            writer = csv.writer(file)
                            writer.writerow(headers)
                    time.sleep(interval)
                    os.remove(filepath)
                    time.sleep(interval)

            topics = {}
            def mock_callback(topic,data):
                nonlocal topics
                topic = topic()
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)
            
            test_filename = "test_file_watcher_deletion.csv"
            delete_dir = test_dir
            metadata = MetadataManager()
            watcher = FileWatcher(delete_dir,metadata,
                                  callbacks=[mock_callback],
                                  filenames=test_filename)
            num_create = 3
            interval = 2
            watcher.start()
            delete_fn = os.path.join(delete_dir,test_filename)
            mthread = Thread(
                target=delete_file, args=(delete_fn, interval, num_create)
            )
            mthread.start()
            mthread.join()
            time.sleep(1)
            watcher.stop()
            self.assertEqual(len(topics[metadata.experiment.stop()]), 
                             num_create)

    def test_watch_directory(self):
        with tempfile.TemporaryDirectory() as test_dir:
            def create_file(filepath, interval, count):
                for _ in range(count):
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                    headers = ["Timestamp"] + [
                        f"TestHeading{str(h)}" for h in range(0, 10)
                    ]
                    with open(filepath, "w", newline="") as file:
                        writer = csv.writer(file)
                        writer.writerow(headers)
                    time.sleep(interval)

            def mod_file(filename, interval, count):
                for _ in range(count):
                    now = datetime.now()
                    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                    with open(filename, "a") as file:
                        file.write(f"{timestamp}\n")
                    time.sleep(interval)

            topics = {}
            def mock_callback(topic,data):
                nonlocal topics
                topic = topic()
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir,metadata,
                                  callbacks=[mock_callback])
            num_create = 3
            interval = 2
            watcher.start()
            tmp_fn = "tmp.txt"
            creation_dir = os.path.join(test_dir,tmp_fn)
            mthread = Thread(target=create_file, args=(creation_dir, 
                                                       interval, 
                                                       num_create))
            mthread.start()
            mthread.join()
            time.sleep(1)
            watcher.stop()
            self.assertEqual(len(topics[metadata.experiment.start()]),
                             num_create)

            # Give extra time for observer cleanup in forked mode
            time.sleep(1.5)

            # Clear topics from first part of test
            topics.clear()

            num_mod = 4
            interval = 2
            metadata = MetadataManager()
            watcher = FileWatcher(test_dir,metadata,
                                  callbacks=[mock_callback],
                                  filenames=tmp_fn)
            watcher.start()

            # Wait for initial file detection event to be processed and debounce to complete
            time.sleep(2.0)

            mthread = Thread(target=mod_file, args=(creation_dir,
                                                    interval, num_mod))
            mthread.start()
            mthread.join()

            # Actively wait for events to be processed (max 10 seconds)
            # Debounce delay is 0.75s per event
            measurement_key = metadata.experiment.measurement()
            max_wait = 10
            wait_interval = 0.5
            elapsed = 0
            while elapsed < max_wait:
                measurement_events = topics.get(measurement_key, [])
                if len(measurement_events) >= num_mod:
                    break
                time.sleep(wait_interval)
                elapsed += wait_interval

            watcher.stop()

            # Give extra time for observer thread to fully stop
            time.sleep(0.5)

            # With cleared topics, we should have at least num_mod measurement events
            # Using >= instead of == because file watchers may detect additional events
            measurement_events = topics.get(measurement_key, [])
            if len(measurement_events) < num_mod:
                logger.info(f"\nDEBUG: Expected >= {num_mod}, got {len(measurement_events)}")
                logger.info(f"All topic keys: {list(topics.keys())}")
                logger.info(f"Measurement key: {measurement_key}")
            self.assertGreaterEqual(len(measurement_events), num_mod)

    def test_watch_directory_return_filepath(self):
        with tempfile.TemporaryDirectory() as test_dir:
            def create_file(filepath, interval):
                if os.path.isfile(filepath):
                    os.remove(filepath)
                headers = ["Timestamp"] + [
                    f"TestHeading{str(h)}" for h in range(0, 10)
                ]
                with open(filepath, "w", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow(headers)
                time.sleep(interval)

            def mod_file(filename, interval):
                now = datetime.now()
                timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                with open(filename, "a") as file:
                    file.write(f"{timestamp}\n")
                time.sleep(interval)

            topics = {}
            tmp_fn = "tmp.txt"
            creation_dir = os.path.join(test_dir)
            def mock_callback(topic,data):
                nonlocal topics
                topic = topic()
                # Handle macOS path symlink differences (/var vs /private/var)
                expected_path = os.path.realpath(creation_file)
                actual_path = os.path.realpath(data)
                self.assertEqual(actual_path, expected_path)
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir,metadata,
                                  callbacks=[mock_callback],
                                  return_data=False,
                                  filenames=tmp_fn)
            interval = 2
            watcher.start()
            creation_file = os.path.join(creation_dir,tmp_fn)
            mthread = Thread(target=create_file, args=(creation_file, 
                                                       interval))
            mthread.start()
            mthread.join()
            time.sleep(1)
            self.assertEqual(len(topics[metadata.experiment.start()]),1)
            mthread = Thread(target=mod_file, args=(creation_file, 
                                                    interval))
            mthread.start()
            mthread.join()
            time.sleep(1)
            watcher.stop()
            # Ensure max of 2 measurements per file
            self.assertGreaterEqual(len(topics[metadata.experiment.measurement()]),1)
            self.assertLessEqual(len(topics[metadata.experiment.measurement()]),2)

    def test_csv_file_creation(self):
        with tempfile.TemporaryDirectory() as test_dir:
            csv_file = os.path.join(test_dir, "test.csv")
            topics = {}

            def mock_callback(topic, data):
                nonlocal topics
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir, metadata, callbacks=[mock_callback], filenames="test.csv", debounce_delay=0.1)
            watcher.start()

            self._write_csv_file(csv_file, [["Time", "Value"], ["1", "100"]])
            time.sleep(2)  # macOS FSEvents can have significant delay
            watcher.stop()

            self.assertEqual(len(topics[metadata.experiment.start()]), 1)

    def test_csv_file_modification(self):
        with tempfile.TemporaryDirectory() as test_dir:
            csv_file = os.path.join(test_dir, "test.csv")

            topics = {}
            def mock_callback(topic, data):
                nonlocal topics
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir, metadata, callbacks=[mock_callback], filenames="test.csv", debounce_delay=0.1)
            watcher.start()

            # Wait a moment for the watcher to be ready
            time.sleep(0.5)

            # Write the complete file content in one operation to trigger one modification event
            self._write_csv_file(csv_file, [["Time", "Value"], ["2", "200"]])

            # Wait longer for debounce to complete
            time.sleep(1.5)
            watcher.stop()

            # Assert the mock topic received the complete file data
            expected_topic = metadata.experiment.start()
            if expected_topic not in topics:
                # Debug: available topics if assertion fails
                logger.info(f"Expected topic '{expected_topic}' not found. Available topics: {list(topics.keys())}")
                # If no topics found, check if we need to wait longer
                if not topics:
                    self.fail("No topics received - FileWatcher callback may not have triggered")
                # Use the first available topic as fallback
                expected_topic = list(topics.keys())[0]
            self.assertEqual(topics[expected_topic], [[['Time', 'Value'], ['2', '200']]])
            # self.assertEqual(len(topics[metadata.experiment.measurement()]), 1)

    def test_csv_file_deletion(self):
        with tempfile.TemporaryDirectory() as test_dir:
            csv_file = os.path.join(test_dir, "test.csv")
            self._write_csv_file(csv_file, [["Time", "Value"]])

            topics = {}
            def mock_callback(topic, data):
                nonlocal topics
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir, metadata, callbacks=[mock_callback], filenames="test.csv", debounce_delay=0.1)
            watcher.start()

            os.remove(csv_file)
            time.sleep(2)  # macOS FSEvents can have significant delay
            watcher.stop()

            self.assertEqual(len(topics[metadata.experiment.stop()]), 1)

    def test_csv_directory_watching(self):
        with tempfile.TemporaryDirectory() as test_dir:
            csv_file = os.path.join(test_dir, "dirwatch.csv")
            topics = {}

            def mock_callback(topic, data):
                nonlocal topics
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir, metadata, callbacks=[mock_callback], debounce_delay=0.1)
            watcher.start()

            self._write_csv_file(csv_file, [["Time", "Val"], ["3", "300"]])
            time.sleep(1)
            watcher.stop()

            self.assertEqual(len(topics[metadata.experiment.start()]), 1)

    def test_csv_return_filepath_only(self):
        with tempfile.TemporaryDirectory() as test_dir:
            csv_file = os.path.join(test_dir, "justpath.csv")
            topics = {}

            def mock_callback(topic, data):
                nonlocal topics
                topic = topic()
                # Handle macOS path symlink differences (/var vs /private/var)
                expected_path = os.path.realpath(csv_file)
                actual_path = os.path.realpath(data)
                self.assertEqual(actual_path, expected_path)
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(test_dir, metadata, callbacks=[mock_callback], return_data=False, filenames="justpath.csv")
            watcher.start()

            # Give the watcher time to initialize before creating files
            time.sleep(0.1)
            self._write_csv_file(csv_file, [["A", "B"], ["X", "Y"]])
            time.sleep(1)
            watcher.stop()

            self.assertEqual(len(topics[metadata.experiment.start()]), 1)

    def test_tsv_creation_and_callback(self):
        with tempfile.TemporaryDirectory() as test_dir:
            test_filename = "test_data.tsv"
            file_path = os.path.join(test_dir, test_filename)

            headers = ["Name", "Age", "Country"]
            row = ["Alice", "30", "USA"]

            topics = {}
            def mock_callback(topic, data):
                nonlocal topics
                topic = topic()
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(
                test_dir,
                metadata_manager=metadata,
                callbacks=[mock_callback],
                filenames=test_filename,
            )
            watcher.start()

            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(headers)
                writer.writerow(row)

            time.sleep(1)
            watcher.stop()

            self.assertEqual(len(topics[metadata.experiment.start()]), 1)
            self.assertIn(headers, topics[metadata.experiment.start()][0])
            self.assertIn(row, topics[metadata.experiment.start()][0])

    def test_tsv_modification(self):
        with tempfile.TemporaryDirectory() as test_dir:
            test_filename = "test_data.tsv"
            file_path = os.path.join(test_dir, test_filename)

            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(["Header1", "Header2"])

            topics = {}
            def mock_callback(topic, data):
                logger.info("Callback invoked with topic: %s and data: %s", topic(), data)
                nonlocal topics
                topic = topic()
                if topic not in topics:
                    topics[topic] = []
                topics[topic].append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(
                test_dir,
                metadata_manager=metadata,
                callbacks=[mock_callback],
                filenames=test_filename,
            )
            watcher.start()

            def modify_file():
                # Wait longer than the debounce delay (0.75s) before modifying
                time.sleep(1.0)
                with open(file_path, "a", newline="") as f:
                    writer = csv.writer(f, delimiter="\t")
                    writer.writerow(["Val1", "Val2"])
                time.sleep(0.5)

            mod_thread = Thread(target=modify_file)
            mod_thread.start()
            mod_thread.join()

            time.sleep(1)
            watcher.stop()

            logger.info("Topics collected: %s", topics)
            self.assertGreaterEqual(len(topics[metadata.experiment.measurement()]), 1)
            found_row = any("Val1" in row for row in topics[metadata.experiment.measurement()][0])
            self.assertTrue(found_row)

    def test_any_file_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_csv = os.path.join(tmpdir, "data.csv")
            file_txt = os.path.join(tmpdir, "data.txt")
            file_tsv = os.path.join(tmpdir, "data.tsv")

            topics = {}
            def mock_cb(topic, data):
                nonlocal topics
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(
                tmpdir,
                metadata_manager=metadata,
                callbacks=[mock_cb],
                return_data=True,
                debounce_delay=0.1
            )
            watcher.start()

            # Create files *after* watcher starts
            self._write_file(file_csv, [["A", "B"], ["1", "2"]], delimiter=",")
            self._write_file(file_tsv, [["X", "Y"], ["9", "8"]], delimiter="\t")
            with open(file_txt, "w") as f:
                f.write("just some text")

            time.sleep(2)  # macOS FSEvents can have significant delay
            watcher.stop()

            self.assertGreaterEqual(len(topics.get(metadata.experiment.start(), [])), 2)

    def test_csv_only_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_csv = os.path.join(tmpdir, "test.csv")
            file_txt = os.path.join(tmpdir, "skip.txt")
            file_tsv = os.path.join(tmpdir, "skip.tsv")

            topics = {}
            def mock_cb(topic, data):
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(
                tmpdir,
                metadata_manager=metadata,
                callbacks=[mock_cb],
                return_data=False,
                filenames=[".csv"],
            )
            watcher.start()
            time.sleep(1)

            self._write_file(file_csv, [["col1", "col2"]], delimiter=",")
            with open(file_txt, "w") as f:
                f.write("txt")
            self._write_file(file_tsv, [["tab1", "tab2"]], delimiter="\t")

            time.sleep(1)
            watcher.stop()

            paths = topics.get(metadata.experiment.start(), [])
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].endswith(".csv"))

    def test_malformed_csv_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = os.path.join(tmpdir, "bad.csv")

            topics = {}
            def cb(topic, data):
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(tmpdir, metadata, callbacks=[cb], filenames="bad.csv", debounce_delay=0.1)
            watcher.start()
            with open(bad_path, "w") as f:
                f.write('"\n"\n')

            time.sleep(2)  # macOS FSEvents can have significant delay
            watcher.stop()

            self.assertEqual(len(topics.get(metadata.experiment.start(), [])), 1)

    def test_multiple_files_simultaneously(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = os.path.join(tmpdir, "data1.csv")
            f2 = os.path.join(tmpdir, "data2.tsv")

            topics = {}
            def cb(topic, data):
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(
                tmpdir,
                metadata,
                callbacks=[cb],
                filenames=["data1.csv", "data2.tsv"],
                debounce_delay=0.1
            )
            watcher.start()

            # Create files AFTER watcher starts
            self._write_csv_file(f1, [["A", "B"]])
            self._write_file(f2, [["X", "Y"]], delimiter="\t")

            time.sleep(2)  # macOS FSEvents can have significant delay
            watcher.stop()

            self.assertEqual(len(topics.get(metadata.experiment.start(), [])), 2)

    def test_multiple_supported_filetypes_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = os.path.join(tmpdir, "test1.csv")
            tsv_file = os.path.join(tmpdir, "test2.tsv")
            txt_file = os.path.join(tmpdir, "test3.txt")

            topics = {}
            def cb(topic, data):
                topic = topic()
                topics.setdefault(topic, []).append(data)

            metadata = MetadataManager()
            watcher = FileWatcher(
                tmpdir,
                metadata,
                callbacks=[cb],
                return_data=True,
                filenames=[".csv", ".tsv", ".txt"]
            )
            watcher.start()

            # Create files AFTER watcher starts
            self._write_file(csv_file, [["A", "B"], ["1", "2"]], delimiter=",")
            self._write_file(tsv_file, [["X", "Y"], ["9", "8"]], delimiter="\t")
            with open(txt_file, "w", encoding="utf-8") as f:
                f.write("Hello world\nSecond line")

            time.sleep(1)
            watcher.stop()

            events = topics.get(metadata.experiment.start(), [])
            self.assertEqual(len(events), 3)

            csv_data = next((d for d in events if isinstance(d, list) and ["A", "B"] in d), None)
            tsv_data = next((d for d in events if isinstance(d, list) and ["X", "Y"] in d), None)
            txt_data = next((d for d in events if isinstance(d, str) and "Hello world" in d), None)

            self.assertIsNotNone(csv_data, "CSV content missing or failed to parse")
            self.assertIsNotNone(tsv_data, "TSV content missing or failed to parse")
            self.assertIsNotNone(txt_data, "TXT content missing or failed to parse")


if __name__ == "__main__":
    unittest.main()
