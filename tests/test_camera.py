"""The slew limiter can never be exceeded."""

import numpy as np

from anantham.config import from_dict
from anantham.sim.camera import PanTiltCamera


def test_slew_limit_never_exceeded():
    cfg = from_dict({"camera": {"max_pan_rate_deg_s": 5.0, "max_tilt_rate_deg_s": 7.0}})
    cam = PanTiltCamera(cfg.camera)
    rng = np.random.default_rng(0)
    for _ in range(2000):
        p0, t0 = cam.pan, cam.tilt
        cam.command(*rng.normal(0, 50, 2))
        assert abs(cam.pan - p0) <= 5.0 / 30 + 1e-12
        assert abs(cam.tilt - t0) <= 7.0 / 30 + 1e-12
        assert abs(cam.pan) <= cam.pan_limit + 1e-9 and abs(cam.tilt) <= cam.tilt_limit + 1e-9


def test_latency_queue():
    cfg = from_dict({"camera": {"command_latency_frames": 2}})
    cam = PanTiltCamera(cfg.camera)
    cam.command(5, 0)
    cam.command(5, 0)
    assert cam.pan == 0.0
    cam.command(0, 0)
    assert cam.pan > 0
