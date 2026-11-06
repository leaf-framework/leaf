import os
import sys
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.register.metadata import MetadataManager
from leaf.register.topic_utilities import topic_utilities


class TestMetadataManager(unittest.TestCase):
    def setUp(self):
        self.manager = MetadataManager()

    def test_add_equipment_data_and_validity(self):
        self.manager.add_instance_data({"organisation": "myInst", "department": "dept", "instance_id": "ABC"})

        self.manager.add_equipment_data({"adapter_id": "EQ123"})
        self.assertTrue(self.manager.is_valid())
        self.assertEqual(self.manager.get_instance_id(), "ABC")

    def test_missing_metadata(self):
        self.manager.add_equipment_data({"organisation": "myInst", "department": "myDept"})
        self.assertFalse(self.manager.is_valid())

        missing = self.manager.get_missing_metadata()
        self.assertGreater(len(missing), 0)

    def test_dot_based_details_topic(self):
        self.manager.add_instance_data({"organisation": "myInst", "department": "myDept", "instance_id": "ABC"})

        self.manager.add_equipment_data({"adapter_id": "EQ123"})
        topic_str = self.manager.details()
        print(topic_str)
        parsed = topic_utilities.parse_topic(topic_str)
        self.assertEqual(parsed.organisation, "myInst")
        self.assertEqual(parsed.adapter_id, "EQ123")
        self.assertEqual(parsed.instance_id, "ABC")
        self.assertEqual(parsed.action, "details")

    def test_dot_based_experiment_start(self):
        self.manager.add_equipment_data(
            {"organisation": "myInst", "department": "myDept", "adapter_id": "EQ123", "instance_id": "ABC"}
        )

        topic_str = self.manager.start()

        parsed = topic_utilities.parse_topic(topic_str)
        self.assertEqual(parsed.organisation, "myInst")
        self.assertEqual(parsed.adapter_id, "EQ123")
        self.assertEqual(parsed.instance_id, "ABC")
        self.assertEqual(parsed.action, "start")

    def test_dot_based_overrides(self):
        """
        Demonstrate that we can override a key like 'instance_id' at call time.
        """
        self.manager.add_equipment_data(
            {"organisation": "myInst", "department": "myDept", "adapter_id": "EQ123", "instance_id": "ABC"}
        )

        topic_str = self.manager.stop(instance_id="OVERRIDE123")

        parsed = topic_utilities.parse_topic(topic_str)
        self.assertEqual(parsed.instance_id, "OVERRIDE123")
        self.assertEqual(parsed.action, "stop")

    def test_get_topics(self):
        mock_md = {
            "organisation": "organisation_id",
            "department": "department_id",
            "adapter_id": "adapter_id",
            "instance_id": "instance_id",
        }
        md = MetadataManager()
        md.add_equipment_data(mock_md)

        template_suffixes = [
            "start",
            "stop",
            "measurement",
            "error",
            "details",
            "running",
        ]
        for suffixes in template_suffixes:
            manager_template = eval(f"self.manager.{suffixes}()")
            topic_template = eval(f"topic_utilities.{suffixes}()")
            self.assertEqual(manager_template, topic_template)

            md_topic = eval(f"md.{suffixes}()")
            if suffixes != "measurement":
                self.assertTrue(topic_utilities.is_complete_topic(md_topic))
            self.assertTrue(topic_utilities.is_instance(md_topic, manager_template))


if __name__ == "__main__":
    unittest.main()
