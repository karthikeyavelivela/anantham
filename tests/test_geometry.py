"""Pixel <-> angle conversion (pinhole)."""

import math

import pytest

from anantham.geometry import CameraGeometry


def test_default_conversion():
    g = CameraGeometry(640, 480, 4.0, 3.0)
    assert g.ifov_h_deg == pytest.approx(0.00625)
    assert g.ifov_urad == pytest.approx(109.08, abs=0.05)
    assert g.rate_deg_s_to_px_frame(5.0, 30.0) == pytest.approx(26.667, abs=1e-3)
    # pinhole: 1 px at the centre ≈ nominal IFOV
    assert math.degrees(math.atan(1 / g.fx)) == pytest.approx(0.00625, rel=1e-3)
    # the image edge maps exactly to half the FOV
    assert g.offset_px_to_deg(320, 240)[0] == pytest.approx(2.0, abs=1e-9)
    assert g.offset_px_to_deg(320, 240)[1] == pytest.approx(1.5, abs=1e-9)


def test_round_trip():
    g = CameraGeometry(640, 480, 4.0, 3.0)
    for x, y in [(0.5, 0.5), (320, 240), (639.5, 479.5), (100.25, 400.75)]:
        u, v = g.image_to_pointing(x, y, 1000.0, 900.0)
        x2, y2 = g.pointing_to_image(u, v, 1000.0, 900.0)
        assert x2 == pytest.approx(x, abs=1e-9) and y2 == pytest.approx(y, abs=1e-9)
    assert "109.1 µrad" in g.conversion_text(30, 5, 5)
