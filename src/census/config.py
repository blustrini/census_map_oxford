"""Shared YAML structure validation; each map validates its own setting values."""

from pathlib import Path
from typing import Any

import yaml


def load_config(
    path: Path, expected_keys: set[str], optional_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Read a YAML mapping and reject missing, unknown, or non-string keys."""
    try:
        with path.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML in {path}: {error}") from error

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    if not all(isinstance(key, str) for key in config):
        raise ValueError("Configuration keys must be strings")
    missing = expected_keys - config.keys()
    unexpected = config.keys() - expected_keys - (optional_keys or set())
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing settings: {sorted(missing)}")
        if unexpected:
            details.append(f"unknown settings: {sorted(unexpected)}")
        raise ValueError("Invalid configuration (" + "; ".join(details) + ")")
    return config
