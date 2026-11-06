import os
import sys
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.register.metadata import MetadataManager
from leaf.register.topic_utilities import Topic, topic_utilities


class TestTopicUtility(unittest.TestCase):
    def test_flattened_templates(self):
        """
        Confirm that the YAML was read and flattened into topic_utilities._templates properly.
        Check that the keys and values look as expected.
        """
        flattened = topic_utilities._templates
        self.assertIn("details", flattened)
        self.assertIn("start", flattened)
        self.assertIn("stop", flattened)
        self.assertIn("measurement", flattened)
        self.assertEqual(flattened["details"], "<root>/<organisation>/<department>/<adapter_id>/<instance_id>/details")
        # A run starts and stops on the instance itself; "experiment" is only the API name
        self.assertEqual(flattened["start"], "<root>/<organisation>/<department>/<adapter_id>/<instance_id>/start")
        self.assertEqual(flattened["stop"], "<root>/<organisation>/<department>/<adapter_id>/<instance_id>/stop")
        self.assertEqual(
            flattened["measurement"],
            "<root>/<organisation>/<department>/<adapter_id>/<instance_id>/measurement/<entity>/<measurement>",
        )

    def test_parse_topic_valid(self):
        """
        Test parse_topic with a valid topic that should match one of the YAML templates.
        """
        topic_str = "myUni/dep2/eq1/abc/details"
        topic_obj = topic_utilities.parse_topic(topic_str)
        self.assertIsInstance(topic_obj, Topic)
        self.assertEqual(topic_obj["organisation"], "myUni")
        self.assertEqual(topic_obj["department"], "dep2")
        self.assertEqual(topic_obj["adapter_id"], "eq1")
        self.assertEqual(topic_obj["instance_id"], "abc")

    def test_parse_topic_root_valid(self):
        """
        Test parse_topic with a valid topic that should match one of the YAML templates.
        """
        topic_str = "rooting/myUni/dep1/eq1/abc/details"
        topic_obj = topic_utilities.parse_topic(topic_str)
        self.assertIsInstance(topic_obj, Topic)
        self.assertEqual(topic_obj["root"], "rooting")
        self.assertEqual(topic_obj["organisation"], "myUni")
        self.assertEqual(topic_obj["department"], "dep1")
        self.assertEqual(topic_obj["adapter_id"], "eq1")
        self.assertEqual(topic_obj["instance_id"], "abc")

    def test_parse_topic_measurement(self):
        """The entity (the instance itself, or e.g. a reactor in it) sits between measurement and the metric."""
        for topic_str, root in (
            ("uniX/dep01/eq99/i7/measurement/reactor_1/temp", None),
            ("demo/uniX/dep01/eq99/i7/measurement/reactor_1/temp", "demo"),
        ):
            topic_obj = topic_utilities.parse_topic(topic_str)
            self.assertEqual(topic_obj["root"], root)
            self.assertEqual(topic_obj["organisation"], "uniX")
            self.assertEqual(topic_obj["department"], "dep01")
            self.assertEqual(topic_obj["adapter_id"], "eq99")
            self.assertEqual(topic_obj["instance_id"], "i7")
            self.assertEqual(topic_obj["entity"], "reactor_1")
            self.assertEqual(topic_obj["measurement"], "temp")
            self.assertEqual(topic_obj.action, "measurement")

    def test_parse_topic_no_match(self):
        """
        If a topic doesn't match any template, parse_topic should raise ValueError.
        """
        with self.assertRaises(ValueError):
            topic_utilities.parse_topic("some/invalid/topic/structure")

    def test_is_complete_topic(self):
        """
        Topics containing '+' or '#' are incomplete. Others are complete.
        """
        self.assertTrue(topic_utilities.is_complete_topic("myUni/eq/123/details"))
        self.assertFalse(topic_utilities.is_complete_topic("myUni/+/123/details"))
        self.assertFalse(topic_utilities.is_complete_topic("myUni/eq/#"))

    def test_get_topic_data_metadata_manager(self):
        mock_md = {
            "organisation": "organisation_id",
            "adapter_id": "adapter_id",
            "instance_id": "instance_id",
            "department": "department_id",
        }

        md = MetadataManager()
        md.add_equipment_data(mock_md)

        topic = md.details()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, mock_md["organisation"])
        self.assertEqual(topic_obj.adapter_id, mock_md["adapter_id"])
        self.assertEqual(topic_obj.instance_id, mock_md["instance_id"])
        self.assertEqual(topic_obj.action, "details")
        self.assertTrue(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.details()))

        topic = md.running()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, mock_md["organisation"])
        self.assertEqual(topic_obj.adapter_id, mock_md["adapter_id"])
        self.assertEqual(topic_obj.instance_id, mock_md["instance_id"])
        self.assertEqual(topic_obj.action, "running")
        self.assertTrue(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.running()))

        topic = md.start()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, mock_md["organisation"])
        self.assertEqual(topic_obj.adapter_id, mock_md["adapter_id"])
        self.assertEqual(topic_obj.instance_id, mock_md["instance_id"])
        self.assertEqual(topic_obj.action, "start")
        self.assertTrue(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.start()))

        topic = md.stop()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, mock_md["organisation"])
        self.assertEqual(topic_obj.adapter_id, mock_md["adapter_id"])
        self.assertEqual(topic_obj.instance_id, mock_md["instance_id"])
        self.assertEqual(topic_obj.action, "stop")
        self.assertTrue(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.stop()))

        topic = md.measurement(experiment_id="test_exp", measurement="test_mes")
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, mock_md["organisation"])
        self.assertEqual(topic_obj.adapter_id, mock_md["adapter_id"])
        self.assertEqual(topic_obj.instance_id, mock_md["instance_id"])
        self.assertEqual(topic_obj.action, "measurement")
        self.assertTrue(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.measurement()))

    def test_get_topic_data_template(self):
        topic = topic_utilities.details()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, "+")
        self.assertEqual(topic_obj.adapter_id, "+")
        self.assertEqual(topic_obj.instance_id, "+")
        self.assertEqual(topic_obj.action, "details")
        self.assertFalse(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.details()))

        topic = topic_utilities.running()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, "+")
        self.assertEqual(topic_obj.adapter_id, "+")
        self.assertEqual(topic_obj.instance_id, "+")
        self.assertEqual(topic_obj.action, "running")
        self.assertFalse(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.running()))

        topic = topic_utilities.start()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, "+")
        self.assertEqual(topic_obj.adapter_id, "+")
        self.assertEqual(topic_obj.instance_id, "+")
        self.assertEqual(topic_obj.action, "start")
        self.assertFalse(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.start()))

        topic = topic_utilities.stop()
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, "+")
        self.assertEqual(topic_obj.adapter_id, "+")
        self.assertEqual(topic_obj.instance_id, "+")
        self.assertEqual(topic_obj.action, "stop")
        self.assertFalse(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.stop()))

        topic = topic_utilities.measurement(experiment_id="test_exp", measurement="test_mes")
        topic_obj = topic_utilities.parse_topic(topic)
        self.assertEqual(topic_obj.organisation, "+")
        self.assertEqual(topic_obj.adapter_id, "+")
        self.assertEqual(topic_obj.instance_id, "+")
        self.assertEqual(topic_obj.action, "measurement")
        self.assertFalse(topic_utilities.is_complete_topic(topic))
        self.assertTrue(topic_utilities.is_instance(topic, topic_utilities.measurement()))
