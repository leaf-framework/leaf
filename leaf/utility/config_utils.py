"""
Utility functions for configuration file handling.
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

# Passwords the UI wizard stores beside the config, so the config itself only holds ${VAR}.
SECRETS_FILE = "secrets.env"
# ${VAR_NAME} or ${VAR_NAME:default_value}
ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


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
        if ":" in var_expr:
            var_name, default_value = var_expr.split(":", 1)
            value = os.environ.get(var_name.strip(), default_value.strip())
        else:
            var_name = var_expr.strip()
            value = os.environ.get(var_name)
            if value is None:
                raise ValueError(f"Environment variable '{var_name}' not found and no default value provided")

        return value

    return ENV_PATTERN.sub(replace_var, content)


def _read_secrets(path: Path) -> dict[str, str]:
    secrets: dict[str, str] = {}
    if not path.exists():
        return secrets
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        secrets[key.strip()] = value
    return secrets


def load_secrets(config_path: str | Path) -> None:
    """Put the secrets.env next to the config into the environment; a variable already set wins."""
    for key, value in _read_secrets(Path(config_path).parent / SECRETS_FILE).items():
        _ = os.environ.setdefault(key, value)


def store_secret(config_path: str | Path, name: str, value: str) -> str:
    """Save value in secrets.env under a free variable name based on name; returns the ${VAR} for the config."""
    path = Path(config_path).parent / SECRETS_FILE
    taken = _read_secrets(path)
    var = name
    count = 2
    # A name already in the environment would hide the stored value, as load_secrets lets the environment win
    while var in taken or var in os.environ:
        var = f"{name}_{count}"
        count += 1
    # Created owner-only, so other users on the LEAF machine cannot read it
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as secrets:
        _ = secrets.write(f"{var}={value}\n")
    os.environ[var] = value
    return "${" + var + "}"


def substitute_in_config(value: Any) -> Any:
    """Substitute ${VAR} in the strings of a parsed config, so a value with YAML syntax (": ", " #", "!") stays as is."""
    if isinstance(value, dict):
        return {key: substitute_in_config(item) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute_in_config(item) for item in value]
    if not isinstance(value, str):
        return value
    substituted = substitute_env_variables(value)
    if ENV_PATTERN.fullmatch(value) is None:
        return substituted
    # port: ${PORT} still gives a number, as it did when substitution ran before parsing
    try:
        typed = yaml.safe_load(substituted)
    except yaml.YAMLError:
        return substituted
    if isinstance(typed, (bool, int, float)):
        return typed
    return substituted
