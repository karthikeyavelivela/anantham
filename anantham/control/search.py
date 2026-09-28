"""Acquisition and recovery search patterns (sections 4.9 and 4.10).

* Global search: square spiral from the screen centre, one ~85 %-FOV step at a time.
* Local recovery: small square spiral around the Kalman prediction.
* Optional wide-FOV acquisition: a separate fixed sensor sees the whole screen at 1/N
  resolution; after ``wide_confirm_frames`` consistent detections it hands the position
  to the narrow camera, which must still confirm with N frames.

The worst-case search time of the spiral is computed analytically and logged.
"""

from __future__ import annotations

import math

import numpy as np

from ..config.schema import PerceptionConfig
from ..perception.classical import ClassicalDetector


def square_spiral(centre: tuple[float, float], step: tuple[float, float], rings: int,
                  bounds: tuple[float, float, float, float] | None = None) -> list[np.ndarray]:
    """Waypoints of a square spiral (right, down, left×2, up×2, …) clipped to ``bounds``."""
    cx, cy = centre
    dx, dy = step
    pts = [np.array([cx, cy])]
    x, y = 0, 0
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    leg, d = 1, 0
    while max(abs(x), abs(y)) <= rings:
        for _ in range(2):
            ux, uy = dirs[d % 4]
            x, y = x + ux * leg, y + uy * leg
            pts.append(np.array([cx + x * dx, cy + y * dy]))
            d += 1
        leg += 1
    # the last leg overshoots one ring; clamp it so the outer ring is completed
    lim = np.array([rings * dx, rings * dy])
    c = np.array([cx, cy])
    pts = [c + np.clip(p - c, -lim, lim) for p in pts]
    if bounds is not None:
        x0, y0, x1, y1 = bounds
        pts = [np.array([min(max(p[0], x0), x1), min(max(p[1], y0), y1)]) for p in pts]
    out: list[np.ndarray] = []
    for p in pts:
        if out and np.hypot(*(p - out[-1])) <= 1.0:
            continue
        if any(np.hypot(*(p - q)) <= 1.0 for q in out[:-1]):
            break  # the clamped overshoot leg only revisits the outer ring
        out.append(p)
    return out


def path_time_s(points: list[np.ndarray], start: np.ndarray, umax: tuple[float, float],
                fps: float) -> float:
    """Time to traverse ``points`` from ``start`` with independent per-axis rate limits."""
    frames, cur = 0.0, np.asarray(start, float)
    for p in points:
        d = np.abs(p - cur)
        frames += max(d[0] / umax[0], d[1] / umax[1])
        cur = p
    return frames / fps


class SpiralSearch:
    """Waypoint follower over a (global or local) square spiral."""

    def __init__(self, centre, step, rings, bounds, loop: bool = True):
        self.points = square_spiral(centre, step, rings, bounds)
        self.i = 0
        self.loop = loop
        self.done = False

    def target(self, bore: np.ndarray, tol: float = 1.0) -> np.ndarray:
        """Current waypoint; advances when the boresight is within ``tol`` px of it."""
        while np.all(np.abs(self.points[self.i] - bore) <= tol):
            if self.i + 1 < len(self.points):
                self.i += 1
            elif self.loop:
                self.i = 0
            else:
                self.done = True
                break
        return self.points[self.i]


def global_spiral_rings(screen: tuple[float, float], step: tuple[float, float],
                        fov: tuple[float, float]) -> int:
    """Rings needed so the FOV swept along the spiral covers the whole screen."""
    rx = (screen[0] / 2 - fov[0] / 2) / step[0]
    ry = (screen[1] / 2 - fov[1] / 2) / step[1]
    return max(int(math.ceil(max(rx, ry) - 1e-9)), 1)


class WideAcquisition:
    """OPTIONAL wide-FOV acquisition sensor processing and hand-off."""

    def __init__(self, pcfg: PerceptionConfig, spot_size: float, downscale: float,
                 confirm: int, fps: float):
        self.n = downscale
        self.det = ClassicalDetector(pcfg, max(spot_size / downscale, 1.5))
        self.det.cfg = _small_border(pcfg)
        self.confirm, self.fps = confirm, fps
        self.prev: np.ndarray | None = None
        self.count = 0
        self.vel = np.zeros(2)
        self.tabu: list[tuple[np.ndarray, int]] = []
        self.k = 0

    def add_tabu(self, pos: np.ndarray, frames: int) -> None:
        """Ignore wide detections near ``pos`` (screen px) for ``frames`` frames."""
        self.tabu.append((np.asarray(pos, float), self.k + frames))

    def step(self, wide: np.ndarray, los_offset_px: tuple[float, float] = (0.0, 0.0)
             ) -> tuple[np.ndarray, np.ndarray] | None:
        """Process one wide frame → (screen position, velocity px/frame) or None."""
        self.k += 1
        self.tabu = [(p, until) for p, until in self.tabu if until > self.k]
        res = self.det.detect(wide)
        best = None
        for c in res.candidates:
            if c.edge or c.size_match < 0.5 or c.score < 0.25:
                continue
            pos = np.array([c.x * self.n, c.y * self.n]) - np.asarray(los_offset_px)
            if any(np.hypot(*(pos - p)) < 12 * self.n for p, _ in self.tabu):
                continue
            best = pos
            break
        if best is None:
            self.count, self.prev = 0, None
            return None
        if self.prev is not None and np.hypot(*(best - self.prev)) < 6 * self.n:
            self.vel = best - self.prev
            self.count += 1
        else:
            self.count, self.vel = 1, np.zeros(2)
        self.prev = best
        return (best, self.vel) if self.count >= self.confirm else None


def _small_border(pcfg: PerceptionConfig) -> PerceptionConfig:
    import copy

    c = copy.deepcopy(pcfg)
    c.border_px = 2
    return c
