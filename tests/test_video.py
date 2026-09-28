"""M4: make-video → evaluator MP4 mode round trip, adaptive spot scale, any resolution."""

import csv

import pytest

from anantham.config import from_dict
from anantham.io.video_source import VideoSource
from anantham.perception.scale import estimate_spot_scale
from anantham.pipeline.session import run_video
from anantham.tools_video import make_test_video


def _cfg(**over):
    d = {"perception": {"mode": "classical"}, "run": {"duration_s": 3.0, "seed": 2}}
    for k, v in over.items():
        d.setdefault(k, {}).update(v)
    return from_dict(d)


def test_round_trip_centroid_error_below_1px(tmp_path):
    cfg = _cfg()
    info = make_test_video(cfg, tmp_path / "clean.mp4")
    s, paths = run_video(cfg, info["video"], info["truth"], tmp_path / "out", "clean", pdf=False)
    assert s["acquired"]
    assert s["centroiding_error_px"]["rmse"] < 1.0
    assert s["detection_coverage"] > 0.95
    with open(paths["centroids"], newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == ["frame", "time_s", "x_px", "y_px", "state", "confidence"]
    assert len(rows) == info["frames"]


def test_adaptive_scale_and_resolution(tmp_path):
    cfg = _cfg(camera={"res_w": 960, "res_h": 720, "fov_h_deg": 6.0, "fov_v_deg": 4.5},
               target={"size_px": 16.0, "size_h_px": 16.0})
    info = make_test_video(cfg, tmp_path / "big.mp4")
    src = VideoSource(info["video"], cfg)
    assert (src.width, src.height) == (960, 720)
    est = estimate_spot_scale(src.peek(15), cfg.perception, 10.0)
    assert not est.fallback
    assert est.size_px == pytest.approx(16.0, rel=0.2)
    cfg.target.size_px = 10.0  # the stack must not rely on the configured size in video mode
    s, _ = run_video(cfg, info["video"], info["truth"], None, pdf=False)
    assert s["video"]["spot_size_px"] == pytest.approx(16.0, rel=0.2)
    assert s["centroiding_error_px"]["rmse"] < 1.0
