import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.join(".."))
sys.path.insert(0, os.path.join("..", ".."))
sys.path.insert(0, os.path.join("..", "..", ".."))

from leaf.utility.config_utils import substitute_env_variables


class TestSubstituteEnvVariables(unittest.TestCase):
    """Tests for the substitute_env_variables function."""

    def setUp(self) -> None:
        """Save current environment state."""
        self.env_backup = os.environ.copy()

    def tearDown(self) -> None:
        """Restore environment state."""
        os.environ.clear()
        os.environ.update(self.env_backup)

    def test_basic_substitution(self):
        """Test basic environment variable substitution."""
        os.environ["TEST_VAR"] = "test_value"
        content = "host: ${TEST_VAR}"
        result = substitute_env_variables(content)
        self.assertEqual(result, "host: test_value")

    def test_multiple_substitutions(self):
        """Test multiple environment variables in the same content."""
        os.environ["HOST"] = "localhost"
        os.environ["PORT"] = "6379"
        os.environ["DB"] = "3"
        content = """
OUTPUTS:
  - plugin: KEYDB
    host: ${HOST}
    port: ${PORT}
    db: ${DB}
"""
        result = substitute_env_variables(content)
        self.assertIn("host: localhost", result)
        self.assertIn("port: 6379", result)
        self.assertIn("db: 3", result)

    def test_default_value_used(self):
        """Test that default values are used when variable doesn't exist."""
        content = "host: ${MISSING_VAR:default_host}"
        result = substitute_env_variables(content)
        self.assertEqual(result, "host: default_host")

    def test_default_value_with_colon(self):
        """Test default values containing colons."""
        content = "url: ${DATABASE_URL:postgresql://localhost:5432/db}"
        result = substitute_env_variables(content)
        self.assertEqual(result, "url: postgresql://localhost:5432/db")

    def test_env_var_overrides_default(self):
        """Test that environment variable takes precedence over default."""
        os.environ["REDIS_HOST"] = "redis.example.com"
        content = "host: ${REDIS_HOST:localhost}"
        result = substitute_env_variables(content)
        self.assertEqual(result, "host: redis.example.com")

    def test_missing_var_without_default_raises_error(self):
        """Test that missing variable without default raises ValueError."""
        content = "host: ${MISSING_REQUIRED_VAR}"
        with self.assertRaises(ValueError) as context:
            substitute_env_variables(content)
        self.assertIn("MISSING_REQUIRED_VAR", str(context.exception))
        self.assertIn("not found", str(context.exception))

    def test_whitespace_handling(self):
        """Test that whitespace around variable names and defaults is handled."""
        os.environ["SPACED_VAR"] = "value"
        content = "test: ${ SPACED_VAR }"
        result = substitute_env_variables(content)
        self.assertEqual(result, "test: value")

    def test_whitespace_in_default(self):
        """Test whitespace handling in default values."""
        content = "test: ${ MISSING : default value }"
        result = substitute_env_variables(content)
        self.assertEqual(result, "test: default value")

    def test_empty_string_env_var(self):
        """Test that empty string environment variables are substituted."""
        os.environ["EMPTY_VAR"] = ""
        content = "value: ${EMPTY_VAR}"
        result = substitute_env_variables(content)
        self.assertEqual(result, "value: ")

    def test_no_substitution_needed(self):
        """Test content with no variables remains unchanged."""
        content = "host: localhost\nport: 6379"
        result = substitute_env_variables(content)
        self.assertEqual(result, content)

    def test_yaml_with_env_vars_parses_correctly(self):
        """Test that substituted YAML can be parsed correctly."""
        os.environ["INSTANCE_ID"] = "test_instance"
        os.environ["INSTITUTE"] = "test_institute"
        content = """
EQUIPMENT_INSTANCES:
  - equipment:
      adapter: HelloWorld
      data:
        instance_id: ${INSTANCE_ID}
        institute: ${INSTITUTE:default_institute}
"""
        result = substitute_env_variables(content)
        parsed = yaml.safe_load(result)
        self.assertEqual(parsed["EQUIPMENT_INSTANCES"][0]["equipment"]["data"]["instance_id"], "test_instance")
        self.assertEqual(parsed["EQUIPMENT_INSTANCES"][0]["equipment"]["data"]["institute"], "test_institute")

    def test_numeric_env_var(self):
        """Test numeric environment variables."""
        os.environ["PORT_NUMBER"] = "8080"
        content = "port: ${PORT_NUMBER}"
        result = substitute_env_variables(content)
        self.assertEqual(result, "port: 8080")

    def test_complex_yaml_structure(self):
        """Test complex YAML with multiple nested variables."""
        os.environ["REDIS_HOST"] = "redis.local"
        os.environ["REDIS_PORT"] = "6379"
        content = """
OUTPUTS:
  - plugin: KEYDB
    host: ${REDIS_HOST:localhost}
    port: ${REDIS_PORT:6379}
    db: ${REDIS_DB:0}
  - plugin: FILE
    filename: ${LOG_FILE:output.log}
"""
        result = substitute_env_variables(content)
        parsed = yaml.safe_load(result)
        self.assertEqual(parsed["OUTPUTS"][0]["host"], "redis.local")
        # Note: YAML auto-converts numeric strings to integers
        self.assertEqual(parsed["OUTPUTS"][0]["port"], 6379)
        self.assertEqual(parsed["OUTPUTS"][0]["db"], 0)
        self.assertEqual(parsed["OUTPUTS"][1]["filename"], "output.log")


if __name__ == "__main__":
    unittest.main()
