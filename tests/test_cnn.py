"""ONNX CNN verifier: loads with ONNX Runtime, accepts a beacon, rejects clutter."""

import numpy as np
import pytest

from anantham.perception.cnn import DEFAULT_MODEL, CnnVerifier
from anantham.sim.scene import render_spot

pytestmark = pytest.mark.skipif(not DEFAULT_MODEL.exists(), reason="model not trained")


def _img(rng, beacon=True, star=False):
    img = np.full((200, 200), 30.0, np.float32)
    if beacon:
        render_spot(img, 100.3, 99.6, 150.0, "square", 10.0, 10.0, 0.8)
    if star:
        render_spot(img, 100.0, 100.0, 60.0, "gaussian", 0.0, 0.0, 0.6)
    img += rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_verifier_accepts_and_refines():
    v = CnnVerifier()
    rng = np.random.default_rng(0)
    (p, x, y), = v.verify(_img(rng), [(101.0, 99.0)], 10.0)
    assert p > 0.9
    assert abs(x - 100.3) < 1.0 and abs(y - 99.6) < 1.0


def test_verifier_rejects_noise_and_star():
    v = CnnVerifier()
    rng = np.random.default_rng(1)
    (p1, _, _), = v.verify(_img(rng, beacon=False), [(100.0, 100.0)], 10.0)
    (p2, _, _), = v.verify(_img(rng, beacon=False, star=True), [(100.0, 100.0)], 10.0)
    assert p1 < 0.5 and p2 < 0.5
