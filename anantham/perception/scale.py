"""Adaptive spot scale for external video (section 4.5).

The beacon size in an evaluator video is unknown. We run a scale-agnostic detection
(large top-hat kernel, no size gating) on the first N frames, take the strongest compact
blob of each frame and use the median of its half-max size. All kernels, gates and ROI
sizes are then derived from that estimate — nothing assumes 640×480 or 10 px.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from ..config.schema import PerceptionConfig
from .classical import ClassicalDetector


@dataclass
class ScaleEstimate:
    """Result of the adaptive scale estimation."""

    size_px: float
    n_frames_used: int
    n_frames_with_blob: int
    per_frame: list
    fallback: bool


def estimate_spot_scale(frames: list[np.ndarray], cfg: PerceptionConfig,
                        default_size: float) -> ScaleEstimate:
    """Estimate the designated spot size (sqrt half-max area, px) from ``frames``."""
    if not frames:
        return ScaleEstimate(default_size, 0, 0, [], True)
    h, w = frames[0].shape[:2]
    kernel = int(min(max(min(h, w) / 6.0, 21), 121))
    guess = max((kernel - cfg.tophat_add) / cfg.tophat_factor, 4.0)
    c = copy.deepcopy(cfg)
    c.size_tolerance = 50.0  # disable size gating while estimating
    det = ClassicalDetector(c, guess)
    sizes = []
    for f in frames:
        res = det.detect(f)
        best, best_q = None, 0.0
        for cand in res.candidates:
            if cand.edge or cand.size_est < 2.0:
                continue
            q = cand.snr * cand.compactness
            if q > best_q:
                best, best_q = cand, q
        sizes.append(None if best is None else best.size_est)
    valid = [s for s in sizes if s is not None]
    if not valid:
        return ScaleEstimate(default_size, len(frames), 0, sizes, True)
    return ScaleEstimate(float(np.median(valid)), len(frames), len(valid), sizes, False)
