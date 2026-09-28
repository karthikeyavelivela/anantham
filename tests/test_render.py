"""Sub-pixel renderer: a known centroid is recovered within 0.05 px (noise-free)."""

import numpy as np
import pytest

from anantham.perception.classical import centroid_moment
from anantham.sim.scene import box_profile, render_spot


@pytest.mark.parametrize("size", [5.0, 10.0, 20.0])
@pytest.mark.parametrize("shape", ["square", "gaussian", "circle"])
def test_subpixel_centroid(size, shape):
    rng = np.random.default_rng(1)
    for _ in range(20):
        x, y = rng.uniform(40, 60, 2)
        img = np.zeros((100, 100), np.float32)
        render_spot(img, x, y, 200.0, shape, size, size, 0.8)
        cx, cy = centroid_moment(img)
        assert abs(cx - x) < 0.05 and abs(cy - y) < 0.05, (shape, size, x, y, cx, cy)


def test_box_profile_integrates_to_width():
    edges = np.arange(0, 101, dtype=float)
    p = box_profile(edges, 50.3, 10.0, 0.8)
    assert abs(p.sum() - 10.0) < 1e-6
    assert p.max() <= 1.0 + 1e-9


def test_pixel_centre_convention():
    img = np.zeros((20, 20), np.float32)
    render_spot(img, 10.0, 10.0, 100.0, "square", 2.0, 2.0, 0.05)
    # a 2-px box centred on the pixel corner (10, 10) covers pixels 9 and 10 equally
    assert img[9, 9] == pytest.approx(img[10, 10], rel=1e-6)
    assert img[9, 9] > 95.0  # edge blur of sigma=0.05 costs ~2 % per axis
