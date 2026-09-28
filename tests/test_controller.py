"""Controller: zero steady-state error on constant velocity, slew clamp, anti-windup."""

import numpy as np

from anantham.config import from_dict
from anantham.control.controller import PanTiltController
from anantham.control.search import global_spiral_rings, square_spiral


def test_constant_velocity_tracking():
    c = PanTiltController(from_dict({}).control, (26.7, 26.7))
    p, x, v = np.zeros(2), np.array([50.0, -30.0]), np.array([4.0, 2.0])
    for _ in range(150):
        u = c.track(x, v, p, sigma=0.5)
        assert np.all(np.abs(u) <= 26.7 + 1e-9)
        p = p + u
        x = x + v
    assert np.all(np.abs(x - p) < 0.3)


def test_spiral_covers_screen():
    step = (0.85 * 640, 0.85 * 480)
    r = global_spiral_rings((2000, 2000), step, (640, 480))
    pts = np.array(square_spiral((1000, 1000), step, r, (0, 0, 2000, 2000)))
    # every screen point must be within half a FOV of the swept path
    grid = np.stack(np.meshgrid(np.arange(0, 2001, 50), np.arange(0, 2001, 50)), -1).reshape(-1, 2)
    covered = np.zeros(len(grid), bool)
    for a, b in zip(pts[:-1], pts[1:]):
        for t in np.linspace(0, 1, 60):
            q = a + (b - a) * t
            covered |= (np.abs(grid[:, 0] - q[0]) <= 320) & (np.abs(grid[:, 1] - q[1]) <= 240)
    assert covered.all()
