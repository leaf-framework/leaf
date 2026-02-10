import logging
import os
import tempfile
import threading
import time
import unittest

from leaf.start import main
from leaf.utility.logger.logger_utils import clear_log_buffer, get_log_buffer, get_logger


class TestLogger(unittest.TestCase):
    def test_logger(self):
        # Clear buffer to ensure clean state for this test
        clear_log_buffer()

        logger = get_logger("leaf.test")
        logger.info("test")
        # Not captured by the logger
        logger.debug("test")
        logger.error("test")
        logger.warning("test")
        logger.critical("test")

        # Check deque
        content = get_log_buffer()
        self.assertEqual(4, len(content))

        # Clear buffer
        clear_log_buffer()
        self.assertEqual(0, len(get_log_buffer()))

        # Set level to debug
        logger = get_logger("leaf.debug.test", log_level=logging.DEBUG)
        logger.debug("test")
        self.assertEqual(1, len(get_log_buffer()))

    def test_leaf_startup_logs_captured(self):
        """Test that LEAF startup logs, including the ASCII logo, are captured in the buffer."""
        # Clear buffer before test
        clear_log_buffer()

        # Create a temporary config file with FILE output to avoid network dependencies
        # and prevent os._exit() from being called due to MQTT connection failures
        config_content = """
EQUIPMENT_INSTANCES:
  - equipment:
      adapter: Example
      data:
        instance_id: test_device
        institute: test_lab
      requirements:
        interval: 60

OUTPUTS:
  - plugin: FILE
    filename: test_output.json
"""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_config_path = f.name

        try:

            def run_leaf_with_timeout():
                """Run LEAF and catch exceptions."""
                try:
                    # Run LEAF with --nogui to avoid starting web server
                    # --no-signals prevents signal handlers from interfering with test
                    main(["--nogui", "--no-signals", "--config", temp_config_path])
                except (SystemExit, KeyboardInterrupt):
                    # Expected when shutting down
                    pass
                except Exception as e:
                    # Catch any other exceptions to prevent test failure
                    print(f"LEAF raised exception (expected during test): {e}")

            # Start LEAF in a separate thread
            leaf_thread = threading.Thread(target=run_leaf_with_timeout, daemon=True)

            leaf_thread.start()

            # Wait for LEAF to start and log startup messages
            # The welcome message and ASCII art are logged early, within 1-2 seconds
            time.sleep(2)

            # Get the buffer contents
            buffer_contents = list(get_log_buffer())

            # Join all buffer messages into a single string for easier searching
            all_logs = "\n".join(buffer_contents)

            # Check that the ASCII logo is in the buffer
            # The ASCII logo contains distinctive text like "########: ########:"
            self.assertIn("########:", all_logs, "ASCII logo should be captured in the log buffer during startup")

            # Also check for other expected startup messages
            self.assertIn("Welcome to the LEAF Proxy", all_logs, "Welcome message should be in the buffer")
            self.assertIn("Context arguments parsed", all_logs, "Context arguments message should be in the buffer")

            # Buffer should contain multiple startup messages
            self.assertGreater(len(buffer_contents), 5, "Buffer should contain multiple startup log messages")

            # The thread will continue running but as a daemon it will be cleaned up
            # when the test ends. We don't join it since LEAF doesn't have a clean
            # shutdown mechanism in this test context.
        finally:
            # Clean up temporary config file
            if os.path.exists(temp_config_path):
                os.unlink(temp_config_path)
            # Clean up any output file created by the test
            if os.path.exists("test_output.json"):
                os.unlink("test_output.json")


if __name__ == "__main__":
    unittest.main()
