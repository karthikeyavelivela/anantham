"""Beacon trajectories on the virtual screen (GROUND TRUTH — simulator side only).

All trajectories return screen-pixel positions for frame index ``k``. Stateful
trajectories (random, spiral, figure-8 at constant speed) are generated
incrementally with their own seeded RNG and cached, so any frame can be queried
repeatedly and the sequence is reproducible for a given seed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Box = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


def fold(x: float, a: float, b: float) -> float:
    """Reflect ``x`` into ``[a, b]`` (billiard / triangle-wave folding)."""
    span = b - a
    if span <= 0:
        return a
    y = (x - a) % (2 * span)
    return a + span - abs(y - span)


def tri(x: float) -> float:
    """Unit triangle wave: 0 → 1 → 0 with period 1."""
    f = x % 1.0
    return 2 * f if f < 0.5 else 2 * (1 - f)


class Trajectory:
    """Base class. Subclasses implement ``_pos(k)`` or incremental ``_advance``."""

    def __init__(self) -> None:
        self._cache: list[np.ndarray] = []

    def position(self, k: int) -> np.ndarray:
        """Screen position (x, y) at frame ``k``."""
        return self._pos(k)

    def _pos(self, k: int) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError


class Stationary(Trajectory):
    """A beacon that does not move."""

    def __init__(self, start: np.ndarray) -> None:
        super().__init__()
        self.p = np.asarray(start, float)

    def _pos(self, k: int) -> np.ndarray:
        return self.p.copy()


class Straight(Trajectory):
    """Constant-velocity straight line, reflecting at the box walls."""

    def __init__(self, start: np.ndarray, v: float, box: Box, rng: np.random.Generator):
        super().__init__()
        th = rng.uniform(0, 2 * math.pi)
        self.p0, self.vel, self.box = np.asarray(start, float), v * np.array(
            [math.cos(th), math.sin(th)]), box

    def _pos(self, k: int) -> np.ndarray:
        x0, y0, x1, y1 = self.box
        p = self.p0 + self.vel * k
        return np.array([fold(p[0], x0, x1), fold(p[1], y0, y1)])


class Stepped(Trajectory):
    """Incrementally generated trajectory with a cache."""

    def _advance(self) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def _pos(self, k: int) -> np.ndarray:
        while len(self._cache) <= k:
            self._cache.append(self._advance())
        return self._cache[k].copy()


class Circular(Stepped):
    """Uniform circular motion of radius ``r`` about ``centre``."""

    def __init__(self, centre: np.ndarray, r: float, v: float, phase: float, direction: int):
        super().__init__()
        self.c, self.r, self.w = np.asarray(centre, float), r, direction * v / max(r, 1e-6)
        self.phase = phase
        self.k = 0

    def _advance(self) -> np.ndarray:
        a = self.phase + self.w * self.k
        self.k += 1
        return self.c + self.r * np.array([math.cos(a), math.sin(a)])


class Figure8(Stepped):
    """Lissajous figure-8 ``c + (A sin θ, A/2 sin 2θ)`` traversed at constant speed."""

    def __init__(self, centre: np.ndarray, a: float, v: float, theta0: float):
        super().__init__()
        self.c, self.a, self.v, self.th = np.asarray(centre, float), a, v, theta0

    def _advance(self) -> np.ndarray:
        th = self.th
        p = self.c + np.array([self.a * math.sin(th), 0.5 * self.a * math.sin(2 * th)])
        dp = math.hypot(self.a * math.cos(th), self.a * math.cos(2 * th))
        self.th += self.v / max(dp, 1e-6)
        return p


class RandomWalk(Stepped):
    """Ornstein–Uhlenbeck velocity (RMS speed ``v``, τ = 1.5 s), reflecting walls."""

    def __init__(self, start: np.ndarray, v: float, box: Box, fps: float,
                 rng: np.random.Generator):
        super().__init__()
        self.p = np.asarray(start, float).copy()
        self.rng, self.box, self.sig = rng, box, v
        self.a = math.exp(-1.0 / (1.5 * fps))
        self.vel = rng.normal(0, v / math.sqrt(2), 2)

    def _advance(self) -> np.ndarray:
        out = self.p.copy()
        noise = self.rng.normal(0, 1, 2)
        self.vel = self.a * self.vel + (self.sig / math.sqrt(2)) * math.sqrt(1 - self.a ** 2) * noise
        self.p = self.p + self.vel
        x0, y0, x1, y1 = self.box
        for i, (lo, hi) in enumerate(((x0, x1), (y0, y1))):
            if self.p[i] < lo:
                self.p[i], self.vel[i] = 2 * lo - self.p[i], abs(self.vel[i])
            elif self.p[i] > hi:
                self.p[i], self.vel[i] = 2 * hi - self.p[i], -abs(self.vel[i])
        return out


class Spiral(Stepped):
    """Spiral whose radius sweeps between 0.2·R and R (3 turns each way)."""

    def __init__(self, centre: np.ndarray, r: float, v: float, theta0: float):
        super().__init__()
        self.c, self.R, self.v, self.th = np.asarray(centre, float), r, v, theta0
        self.rmin, self.turns = 0.2 * r, 3.0
        self.th0 = theta0

    def _radius(self, th: float) -> float:
        return self.rmin + (self.R - self.rmin) * tri((th - self.th0) / (4 * math.pi * self.turns))

    def _advance(self) -> np.ndarray:
        th = self.th
        r = self._radius(th)
        p = self.c + r * np.array([math.cos(th), math.sin(th)])
        drdth = (self.R - self.rmin) / (2 * math.pi * self.turns)
        self.th += self.v / math.hypot(r, drdth)
        return p


class Sinusoidal(Trajectory):
    """Horizontal drift (reflecting) with a vertical sinusoid of amplitude ``amp``."""

    def __init__(self, start: np.ndarray, v: float, amp: float, box: Box,
                 rng: np.random.Generator):
        super().__init__()
        self.x0, self.yc = float(start[0]), float(start[1])
        self.vx = 0.8 * v * (1 if rng.random() < 0.5 else -1)
        self.amp, self.box, self.lam = amp, box, 520.0
        self.phase = 0.0

    def _pos(self, k: int) -> np.ndarray:
        x0, y0, x1, y1 = self.box
        x = fold(self.x0 + self.vx * k, x0, x1)
        y = self.yc + self.amp * math.sin(2 * math.pi * (x - x0) / self.lam + self.phase)
        return np.array([x, min(max(y, y0), y1)])


class Waypoints(Stepped):
    """Closed piecewise-linear path through user waypoints at constant speed."""

    def __init__(self, points: list, v: float):
        super().__init__()
        self.pts = [np.asarray(p, float) for p in points]
        self.v = v
        self.seg, self.p = 0, self.pts[0].copy()

    def _advance(self) -> np.ndarray:
        out = self.p.copy()
        step = self.v
        for _ in range(len(self.pts) + 1):
            tgt = self.pts[(self.seg + 1) % len(self.pts)]
            d = tgt - self.p
            dist = float(np.hypot(*d))
            if dist > step or dist == 0:
                if dist > 0:
                    self.p = self.p + d / dist * step
                break
            self.p, step = tgt.copy(), step - dist
            self.seg = (self.seg + 1) % len(self.pts)
        return out


@dataclass
class TrajectorySpec:
    """Everything needed to build a trajectory."""

    motion: str
    speed_px: float
    radius_px: float
    box: Box
    start: np.ndarray | None  # None = random
    waypoints: list
    fps: float


def _fit_centre(start: np.ndarray, r: float, box: Box, toward: np.ndarray) -> np.ndarray:
    """Centre at distance r from start, towards ``toward``, clamped so the path fits."""
    x0, y0, x1, y1 = box
    d = toward - start
    n = float(np.hypot(*d))
    u = d / n if n > 1e-6 else np.array([1.0, 0.0])
    c = start + r * u
    return np.array([min(max(c[0], x0 + r), x1 - r), min(max(c[1], y0 + r), y1 - r)])


def make_trajectory(spec: TrajectorySpec, rng: np.random.Generator) -> Trajectory:
    """Build a trajectory; random starts are drawn from ``rng`` inside ``spec.box``."""
    x0, y0, x1, y1 = spec.box
    bc = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    r = min(spec.radius_px, 0.5 * (x1 - x0) - 1, 0.5 * (y1 - y0) - 1)
    r = max(r, 5.0)
    start = spec.start
    if start is None:
        start = np.array([rng.uniform(x0, x1), rng.uniform(y0, y1)])
    start = np.asarray(start, float)
    m, v = spec.motion, spec.speed_px
    if m == "stationary" or v <= 0:
        return Stationary(start)
    if m == "straight":
        return Straight(start, v, spec.box, rng)
    if m == "circular":
        c = _fit_centre(start, r, spec.box, bc)
        phase = math.atan2(start[1] - c[1], start[0] - c[0])
        return Circular(c, r, v, phase, 1 if rng.random() < 0.5 else -1)
    if m == "figure8":
        a = r
        c = np.array([min(max(start[0], x0 + a), x1 - a), min(max(start[1], y0 + a / 2), y1 - a / 2)])
        return Figure8(c, a, v, 0.0)
    if m == "random":
        return RandomWalk(start, v, spec.box, spec.fps, rng)
    if m == "spiral":
        c = _fit_centre(start, 0.2 * r, spec.box, bc)
        c = np.array([min(max(c[0], x0 + r), x1 - r), min(max(c[1], y0 + r), y1 - r)])
        th0 = math.atan2(start[1] - c[1], start[0] - c[0])
        return Spiral(c, r, v, th0)
    if m == "sinusoidal":
        amp = min(0.5 * r, start[1] - y0, y1 - start[1], 200.0)
        return Sinusoidal(start, v, max(amp, 0.0), spec.box, rng)
    if m == "waypoints":
        pts = spec.waypoints if len(spec.waypoints) >= 2 else [
            list(bc + r * np.array([math.cos(a), math.sin(a)]))
            for a in np.linspace(0, 2 * math.pi, 6)[:-1]]
        return Waypoints(pts, v)
    raise ValueError(f"unknown motion '{m}'")
