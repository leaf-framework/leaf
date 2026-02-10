import os
import sys

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

# Obtain the location of this file
test_dir = os.path.dirname(os.path.abspath(__file__))

with open(test_dir + "/../../test_config.yaml") as file:
    config = yaml.safe_load(file)
broker = config["OUTPUTS"][0]["broker"]
port = int(config["OUTPUTS"][0]["port"])
if "username" in config["OUTPUTS"][0]:
    un = config["OUTPUTS"][0]["username"]
    pw = config["OUTPUTS"][0]["password"]
test_file_dir = "test_dir"
test_file = os.path.join(test_file_dir, "ecoli-GFP-mCherry_inter.csv")
