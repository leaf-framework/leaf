import os
import sys
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.register.abstract_leaf import AbstractLeaf
from leaf.register.metadata import MetadataManager
from leaf.register.topic_utilities import topic_utilities


class MockLeafTool(AbstractLeaf):
    def __init__(self, process_mapping=None):
        super().__init__(process_mapping)

    def process(self, topic, data):
        return super().process(topic, data)


class TestTopicUtility(unittest.TestCase):
    def test_abstract_leaf_mapping(self):
        mock_md = {
            # "root": "root_id",
            "organisation": "organisation_identifier",
            "department": "department_identifier",
            "adapter_id": "adapter_identifier",
            "instance_id": "instance_identifier",
        }

        md = MetadataManager()
        md.add_equipment_data(mock_md)

        start_messages = []

        def mock_start(data, organisation=None, department=None, adapter_id=None, instance_id=None, **kwargs):
            nonlocal start_messages
            start_messages.append((data, organisation, department, adapter_id, instance_id, kwargs))

        stop_messages = []

        def mock_stop(data, organisation=None, department=None, adapter_id=None, instance_id=None, **kwargs):
            nonlocal stop_messages
            stop_messages.append((data, organisation, department, adapter_id, instance_id, kwargs))

        details_messages = []

        def mock_details(data, organisation=None, department=None, adapter_id=None, instance_id=None, **kwargs):
            nonlocal details_messages
            details_messages.append((data, organisation, department, adapter_id, instance_id, kwargs))

        measurement_messages = []

        def mock_measurement(
            data,
            organisation=None,
            department=None,
            adapter_id=None,
            instance_id=None,
            entity=None,
            measurement=None,
        ):
            nonlocal measurement_messages
            measurement_messages.append((data, organisation, department, adapter_id, instance_id, entity, measurement))

        mapping = {topic_utilities.start(): [mock_start], topic_utilities.stop: mock_stop}
        abstract_leaf = MockLeafTool(mapping)

        start_data = {"experiment_id": "test_experiment_id123"}
        abstract_leaf.process(md.start(), start_data)
        self.assertEqual(start_messages[0][0], start_data)
        self.assertEqual(start_messages[0][1], mock_md["organisation"])
        self.assertEqual(start_messages[0][2], mock_md["department"])
        self.assertEqual(start_messages[0][3], mock_md["adapter_id"])
        self.assertEqual(start_messages[0][4], mock_md["instance_id"])
        self.assertEqual(start_messages[0][5], {})

        stop_data = {"experiment_id": "test_experiment_id12345"}
        abstract_leaf.process(md.stop(), stop_data)
        self.assertEqual(stop_messages[0][0], stop_data)
        self.assertEqual(stop_messages[0][1], mock_md["organisation"])
        self.assertEqual(stop_messages[0][2], mock_md["department"])
        self.assertEqual(stop_messages[0][3], mock_md["adapter_id"])
        self.assertEqual(stop_messages[0][4], mock_md["instance_id"])
        self.assertEqual(stop_messages[0][5], {})

        details_template = topic_utilities.details()
        abstract_leaf.add_process(details_template, mock_details)
        details_data = {"test_data": "test_data12345"}
        abstract_leaf.process(md.details(), details_data)
        self.assertEqual(details_messages[0][0], details_data)
        self.assertEqual(details_messages[0][1], mock_md["organisation"])
        self.assertEqual(details_messages[0][2], mock_md["department"])
        self.assertEqual(details_messages[0][3], mock_md["adapter_id"])
        self.assertEqual(details_messages[0][4], mock_md["instance_id"])
        self.assertEqual(details_messages[0][5], {})

        details_template = topic_utilities.measurement()
        abstract_leaf.add_process(details_template, mock_measurement)
        measurement_data = {"test_data": "test_data12345"}
        mock_measurement_id = "test_mes123"
        abstract_leaf.process(md.measurement(measurement=mock_measurement_id), measurement_data)
        self.assertEqual(measurement_messages[0][0], measurement_data)
        self.assertEqual(measurement_messages[0][1], mock_md["organisation"])
        self.assertEqual(measurement_messages[0][2], mock_md["department"])
        self.assertEqual(measurement_messages[0][3], mock_md["adapter_id"])
        self.assertEqual(measurement_messages[0][4], mock_md["instance_id"])
        # Without an entity of its own, a point is about the instance
        self.assertEqual(measurement_messages[0][5], mock_md["instance_id"])
        self.assertEqual(measurement_messages[0][6], mock_measurement_id)
