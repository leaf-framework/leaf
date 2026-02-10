import os
import sys
import unittest

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.error_handler.error_holder import ErrorHolder
from leaf.error_handler.exceptions import AdapterLogicError, LEAFError


class TestErrorHolder(unittest.TestCase):
    def setUp(self):
        self.error_holder = ErrorHolder(adapter_id="test_adapter")

    def test_add_error_and_retrieve(self):
        # Simulate raising and catching an exception.

        self.error_holder.add_error(AdapterLogicError("Test"))

        errors = self.error_holder.get_unseen_errors()
        self.assertEqual(len(errors), 1, "One error should be retrieved")
        # errors[0] is a tuple (exception_obj, traceback_str)
        exception_obj, traceback_str = errors[0]
        self.assertIsInstance(exception_obj, LEAFError)
        self.assertIn("NoneType:", traceback_str, "Traceback should contain the original exception info")

        # Ensure that subsequent calls return no errors (they were cleared).
        errors_after_clearing = self.error_holder.get_unseen_errors()
        self.assertEqual(len(errors_after_clearing), 0, "No errors should remain after clearing")


if __name__ == "__main__":
    unittest.main()
