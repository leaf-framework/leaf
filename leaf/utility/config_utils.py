"""
Utility functions for configuration file handling.
"""

import os
import re


def substitute_env_variables(content: str) -> str:
    """
    Substitute environment variables in the form ${VAR_NAME} or ${VAR_NAME:default_value}.

    Args:
        content: The YAML content as a string

    Returns:
        The content with environment variables substituted

    Raises:
        ValueError: If a required environment variable is not found and no default is provided
    """
    def replace_var(match: re.Match) -> str:
        var_expr = match.group(1)

        # Check if there's a default value (VAR_NAME:default_value)
        if ':' in var_expr:
            var_name, default_value = var_expr.split(':', 1)
            value = os.environ.get(var_name.strip(), default_value.strip())
        else:
            var_name = var_expr.strip()
            value = os.environ.get(var_name)
            if value is None:
                raise ValueError(
                    f"Environment variable '{var_name}' not found and no default value provided"
                )

        return value

    # Pattern matches ${VAR_NAME} or ${VAR_NAME:default_value}
    pattern = r'\$\{([^}]+)\}'
    return re.sub(pattern, replace_var, content)
