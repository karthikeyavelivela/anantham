"""Configuration package: schema, validation, YAML presets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from .schema import (
    Config,
    ConfigError,
    Issue,
    from_dict,
    merge,
    to_dict,
    validate,
)

PRESET_DIR = Path(__file__).resolve().parent / "presets"

__all__ = [
    "Config", "ConfigError", "Issue", "from_dict", "merge", "to_dict", "validate",
    "load_config", "save_config", "list_presets", "load_preset", "config_hash", "PRESET_DIR",
]


def list_presets() -> list[str]:
    """Names of all bundled presets (file stems in ``config/presets``)."""
    return sorted(p.stem for p in PRESET_DIR.glob("*.yaml"))


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def load_preset(name: str) -> Config:
    """Load a bundled preset by name (``default`` is always available)."""
    path = PRESET_DIR / f"{name}.yaml"
    if not path.exists():
        raise ConfigError(f"unknown preset '{name}' (available: {', '.join(list_presets())})")
    return from_dict(_read_yaml(path))


def load_config(path_or_preset: str | Path) -> Config:
    """Load a YAML file path, or a bundled preset name."""
    p = Path(path_or_preset)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return from_dict(_read_yaml(p))
    return load_preset(str(path_or_preset))


def save_config(cfg: Config, path: str | Path) -> None:
    """Write ``cfg`` as YAML (full, explicit form)."""
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(to_dict(cfg), fh, sort_keys=False)


def config_hash(cfg: Config) -> str:
    """Short stable hash of the full configuration (for logs)."""
    blob = json.dumps(to_dict(cfg), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]
