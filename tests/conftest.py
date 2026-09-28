"""Shared test helpers."""

import pytest

from anantham.config import from_dict


@pytest.fixture
def classical_cfg():
    """Default config with the classical detector (no ONNX model needed)."""
    return from_dict({"perception": {"mode": "classical"}})
