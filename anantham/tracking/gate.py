"""Identity checks: signature gate, temporal identity gate helpers and blink-code ID.

* Signature: a track may only *start* from a non-edge candidate with size-match ≥ 0.7
  and may only *associate* candidates with size-match ≥ 0.5.
* Temporal identity gate: CANDIDATE → LOCKED needs N consecutive consistent detections.
* Blink code: the designated beacon dims periodically at a known frequency. Over a
  ≤ 0.5 s window the fraction of intensity variance at that frequency must exceed a
  threshold (steady distractors and noise put their variance elsewhere).
"""

from __future__ import annotations

import math

import numpy as np


def blink_statistic(samples: np.ndarray, fps: float, freq: float) -> tuple[float, float]:
    """(fraction of variance at ``freq``, modulation depth std/mean) of a sample series."""
    x = np.asarray(samples, float)
    n = len(x)
    if n < 4:
        return 0.0, 0.0
    mean = float(x.mean())
    d = x - mean
    var = float((d * d).sum())
    if var <= 1e-9 or mean <= 0:
        return 0.0, 0.0
    ph = np.exp(-2j * np.pi * freq * np.arange(n) / fps)
    X = complex((d * ph).sum())
    frac = 2.0 * abs(X) ** 2 / (n * var)
    return min(frac, 1.0), math.sqrt(var / n) / mean


def blink_window(fps: float, freq: float, max_s: float) -> int:
    """Window length (frames) covering a whole number of blink periods within ``max_s``."""
    period = fps / freq
    n_per = max(int(max_s * fps / period), 1)
    return max(int(round(n_per * period)), 4)


def gated_nearest(pred: np.ndarray, cands: list, gate: float, min_size_match: float,
                  used: set | None = None) -> tuple[int, float]:
    """Index of the best candidate inside ``gate`` of ``pred`` (-1 if none) and its distance.

    Cost = normalised distance − 0.25·score, so between two in-gate blobs the closer,
    better-matching one wins.
    """
    best, best_cost, best_d = -1, math.inf, math.inf
    for i, c in enumerate(cands):
        if used and i in used:
            continue
        if c.size_match < min_size_match or not c.accepted:
            continue
        d = math.hypot(c.u - pred[0], c.v - pred[1])
        if d > gate:
            continue
        cost = d / max(gate, 1e-6) - 0.25 * c.score
        if cost < best_cost:
            best, best_cost, best_d = i, cost, d
    return best, best_d
