"""Domain-randomised ROI dataset for the CNN verifier (section 4.4).

Each sample is a 64×64 grey ROI rendered with the simulator's own spot renderer and
disturbance models, with randomised: spot size (3–22 px), shape, PSF / turbulence
broadening, scintillation, noise (Gaussian, Poisson, salt & pepper), atmosphere
(contrast, airlight, blur, rain streaks), clutter stars, other beacons, and edge
clipping (reflect padding exactly as ``extract_roi`` does at image borders).

Labels
------
* ``score``   1 if a beacon centre lies within ±6 px of the ROI centre, else 0
* ``heat``    16×16 Gaussian (σ = 1 cell) at every beacon centre (not at stars / streaks)
* ``offset``  2×16×16 sub-cell offsets of beacon centres (in cells)
* ``mask``    1 on cells that carry an offset target

About 28 % of samples are negatives (noise only, stars, off-centre beacons, rain streaks,
salt & pepper clusters, elongated blobs).
"""

from __future__ import annotations

import math
from multiprocessing import get_context

import cv2
import numpy as np

from ..perception.cnn import ROI, STRIDE, normalise_roi
from ..sim.scene import render_spot

G = ROI // STRIDE
SHAPES = ("square", "square", "rectangle", "circle", "gaussian")


def _background(rng: np.random.Generator) -> np.ndarray:
    lvl = rng.uniform(5, 110)
    gx, gy = rng.normal(0, 0.15, 2)
    y, x = np.mgrid[0:ROI, 0:ROI].astype(np.float32)
    img = lvl + gx * (x - 32) + gy * (y - 32)
    for _ in range(rng.integers(0, 6)):  # clutter stars
        render_spot(img, rng.uniform(0, ROI), rng.uniform(0, ROI), rng.lognormal(3.2, 0.5),
                    "gaussian", 0.0, 0.0, rng.uniform(0.5, 1.0))
    return img.astype(np.float32)


def _beacon(img, rng, x, y, size, heat_pts):
    shape = SHAPES[rng.integers(len(SHAPES))]
    psf = rng.uniform(0.5, 2.3)
    amp = rng.uniform(25, 220) * math.exp(rng.normal(0, 0.3))
    render_spot(img, x, y, amp, shape, size, size * rng.uniform(0.7, 1.3), psf)
    heat_pts.append((x, y))
    return amp


def _streak(img, rng, through_centre):
    x0, y0 = (32 + rng.normal(0, 3), 32 + rng.normal(0, 3)) if through_centre else rng.uniform(0, 64, 2)
    a = rng.uniform(0, math.pi)
    ln = rng.uniform(10, 45)
    dx, dy = math.cos(a) * ln / 2, math.sin(a) * ln / 2
    layer = np.zeros_like(img)
    cv2.line(layer, (int(x0 - dx), int(y0 - dy)), (int(x0 + dx), int(y0 + dy)),
             float(rng.uniform(20, 120)), int(rng.integers(1, 3)), cv2.LINE_AA)
    img += layer


def _disturb(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    if rng.random() < 0.4:  # atmosphere
        t = rng.uniform(0.3, 1.0)
        img = img * t + rng.uniform(0, 140) * (1 - t)
    if rng.random() < 0.3:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.3, 1.6))
    if rng.random() < 0.15:
        for _ in range(rng.integers(1, 6)):
            _streak(img, rng, False)
    if rng.random() < 0.25:
        img = img * rng.uniform(0.2, 0.6)  # low light
    img = np.clip(img, 0, None)
    if rng.random() < 0.7:
        g = rng.uniform(0.05, 1.5)
        img = rng.poisson(img / g).astype(np.float32) * g
    img = img + rng.normal(0, rng.uniform(0, 20)) * rng.standard_normal(img.shape).astype(np.float32)
    q = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        p = rng.uniform(0.01, 0.12)
        r = rng.random(q.shape)
        q[r < p / 2] = 0
        q[(r >= p / 2) & (r < p)] = 255
    return q


def _edge_clip(q: np.ndarray, rng: np.random.Generator, heat_pts: list) -> np.ndarray:
    """Emulate a ROI at an image border: reflect-pad past a random border line."""
    side = rng.integers(4)
    k = int(rng.integers(8, 30))
    out = q.copy()
    if side == 0:
        out[:, :k] = np.fliplr(q[:, k:2 * k])
        heat_pts[:] = [(x, y) for x, y in heat_pts if x > k]
    elif side == 1:
        out[:, 64 - k:] = np.fliplr(q[:, 64 - 2 * k:64 - k])
        heat_pts[:] = [(x, y) for x, y in heat_pts if x < 64 - k]
    elif side == 2:
        out[:k, :] = np.flipud(q[k:2 * k, :])
        heat_pts[:] = [(x, y) for x, y in heat_pts if y > k]
    else:
        out[64 - k:, :] = np.flipud(q[64 - 2 * k:64 - k, :])
        heat_pts[:] = [(x, y) for x, y in heat_pts if y < 64 - k]
    return out


def make_sample(rng: np.random.Generator) -> tuple:
    """One (roi_float, score, heat, offset, mask) sample."""
    img = _background(rng)
    heat_pts: list = []
    positive = rng.random() > 0.28
    if positive:
        x, y = 32 + rng.uniform(-6, 6, 2)
        _beacon(img, rng, x, y, rng.uniform(3, 22), heat_pts)
    else:
        kind = rng.integers(5)
        if kind == 1:
            for _ in range(rng.integers(1, 4)):
                render_spot(img, 32 + rng.normal(0, 3), 32 + rng.normal(0, 3), rng.uniform(20, 200),
                            "gaussian", 0.0, 0.0, rng.uniform(0.45, 1.0))
        elif kind == 2:
            r, a = rng.uniform(15, 28), rng.uniform(0, 2 * math.pi)
            _beacon(img, rng, 32 + r * math.cos(a), 32 + r * math.sin(a), rng.uniform(3, 14), heat_pts)
        elif kind == 3:
            _streak(img, rng, True)
        elif kind == 4:
            w, h = rng.uniform(1.5, 3), rng.uniform(14, 30)
            if rng.random() < 0.5:
                w, h = h, w
            render_spot(img, 32 + rng.normal(0, 2), 32 + rng.normal(0, 2), rng.uniform(40, 200),
                        "rectangle", w, h, 0.7)
    if rng.random() < 0.3:  # another beacon elsewhere in the ROI
        r, a = rng.uniform(18, 30), rng.uniform(0, 2 * math.pi)
        _beacon(img, rng, 32 + r * math.cos(a), 32 + r * math.sin(a), rng.uniform(3, 14), heat_pts)
    q = _disturb(img, rng)
    if rng.random() < 0.12:
        q = _edge_clip(q, rng, heat_pts)
    score = float(any(abs(x - 32) <= 6.5 and abs(y - 32) <= 6.5 for x, y in heat_pts))
    heat = np.zeros((G, G), np.float32)
    off = np.zeros((2, G, G), np.float32)
    mask = np.zeros((G, G), np.float32)
    gy, gx = np.mgrid[0:G, 0:G]
    for x, y in heat_pts:
        cx, cy = x / STRIDE, y / STRIDE
        ix, iy = int(math.floor(cx)), int(math.floor(cy))
        heat = np.maximum(heat, np.exp(-((gx + 0.5 - cx) ** 2 + (gy + 0.5 - cy) ** 2) / 2.0))
        for jy in range(iy - 1, iy + 2):
            for jx in range(ix - 1, ix + 2):
                if 0 <= jx < G and 0 <= jy < G:
                    off[:, jy, jx] = (cx - jx, cy - jy)
                    mask[jy, jx] = 1.0
    return normalise_roi(q), score, heat, off, mask


def _chunk(args):
    seed, n = args
    rng = np.random.default_rng(seed)
    out = [make_sample(rng) for _ in range(n)]
    return (np.stack([o[0] for o in out]).astype(np.float16), np.array([o[1] for o in out], np.float32),
            np.stack([o[2] for o in out]), np.stack([o[3] for o in out]), np.stack([o[4] for o in out]))


def make_dataset(n: int, seed: int = 0, workers: int = 4) -> dict:
    """Generate ``n`` samples in parallel (deterministic for a given seed and chunking)."""
    chunk = 2000
    jobs = [(seed * 100003 + i, min(chunk, n - i * chunk)) for i in range((n + chunk - 1) // chunk)]
    with get_context("spawn").Pool(workers) as pool:
        parts = pool.map(_chunk, jobs)
    return {k: np.concatenate([p[i] for p in parts]) for i, k in
            enumerate(("x", "score", "heat", "offset", "mask"))}
