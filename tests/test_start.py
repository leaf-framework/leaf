import os
import sys
import tempfile
import time
import unittest
import uuid
from threading import Thread

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.error_handler.error_holder import ErrorHolder
from leaf.registry.registry import discover_from_config
from leaf.start import run_adapters, stop_all_adapters
from leaf.utility.running_utilities import build_output_module

curr_dir: str = os.path.dirname(os.path.realpath(__file__))

with open(os.path.join(curr_dir, "test_config.yaml")) as file:
    config = yaml.safe_load(file)

broker = config["OUTPUTS"][0]["broker"]
port = int(config["OUTPUTS"][0]["port"])
try:
    un = config["OUTPUTS"][0]["username"]
    pw = config["OUTPUTS"][0]["password"]
except KeyError:
    un = None
    pw = None

curr_dir = os.path.dirname(os.path.realpath(__file__))
mock_functional_adapter_path = os.path.join(curr_dir, "mock_functional_adapter")

db_host = "localhost"


class TestStart(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_store_path = os.path.join(self.temp_dir.name, "local.json")

    def test_start_no_mqtt(self):
        error_holder = ErrorHolder()
        instance_id = f"{uuid.uuid4()}"
        institute = f"{uuid.uuid4()}"
        ins = [
            {
                "equipment": {
                    "adapter": "MockFunctionalAdapter",
                    "data": {
                        "instance_id": instance_id,
                        "institute": institute,
                    },
                    "requirements": {"write_file": self.file_store_path},
                }
            }
        ]
        discover_from_config({"EQUIPMENT_INSTANCES": ins}, mock_functional_adapter_path)
        discover_from_config(config, mock_functional_adapter_path)
        file_config = {"OUTPUTS": [{"plugin": "FILE", "filename": "local.json", "fallback": None}]}

        output = build_output_module(file_config, None)

        def _start() -> Thread:
            mthread = Thread(target=run_adapters, args=[ins.copy(), output, error_holder])
            mthread.daemon = True
            mthread.start()
            return mthread

        def _stop(thread: Thread) -> None:
            stop_all_adapters()
            time.sleep(10)

        time.sleep(0.5)
        adapter_thread = _start()
        time.sleep(10)
        time.sleep(5)
        _stop(adapter_thread)


if __name__ == "__main__":
    unittest.main()
