import unittest

import leaf.start


# Create a test case but only local execution
@unittest.skip("Skipping test for local")
class TestLocal(unittest.TestCase):
    def test_local(self) -> None:
        leaf.start.main(["--port", "8081"])
