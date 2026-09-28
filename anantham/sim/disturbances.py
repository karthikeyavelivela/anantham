"""Disturbance models (GROUND TRUTH — simulator side only).

Order of application (section 4.2 of the design):

1. line of sight: platform offset + camera jitter (shifts the whole scene)
2. beacon: turbulence angle-of-arrival offset, scintillation, PSF broadening
3. image: atmosphere → Poisson → Gaussian → salt & pepper
4. 8-bit quantisation
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from ..config.schema import DisturbanceConfig, TurbulenceConfig
from .trajectories import fold, tri

# scint_index (σ_I²), AoA sigma (px), AoA tau (s), PSF broadening sigma (px)
TURBULENCE_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "none": (0.0, 0.0, 0.1, 0.0),
    "weak": (0.05, 0.5, 0.1, 0.3),
    "moderate": (0.2, 1.5, 0.1, 0.8),
    "strong": (0.5, 3.0, 0.1, 1.5),
}

# transmission (contrast), airlight DN, brightness factor, blur sigma px, rain streaks
ATMOSPHERE_PRESETS: dict[str, tuple[float, float, float, float, int]] = {
    "clear": (1.0, 0.0, 1.0, 0.0, 0),
    "haze": (0.7, 70.0, 1.0, 0.7, 0),
    "fog": (0.4, 120.0, 1.0, 1.5, 0),
    "rain": (0.8, 40.0, 0.85, 0.5, 90),
    "low_light": (1.0, 0.0, 0.25, 0.0, 0),
}


@dataclass
class TurbulenceParams:
    """Resolved turbulence parameters."""

    scint_index: float
    aoa_sigma_px: float
    aoa_tau_s: float
    psf_broadening_px: float


def resolve_turbulence(cfg: TurbulenceConfig) -> TurbulenceParams:
    """Preset → parameters (``custom`` uses the explicit fields)."""
    if cfg.preset == "custom":
        return TurbulenceParams(cfg.scint_index, cfg.aoa_sigma_px, cfg.aoa_tau_s,
                                cfg.psf_broadening_px)
    return TurbulenceParams(*TURBULENCE_PRESETS[cfg.preset])


class Turbulence:
    """Per-beacon turbulence: correlated AoA jitter + log-normal scintillation."""

    def __init__(self, params: TurbulenceParams, fps: float, rng: np.random.Generator):
        self.p, self.rng = params, rng
        self.a = math.exp(-1.0 / (fps * max(params.aoa_tau_s, 1e-3)))
        self.aoa = rng.normal(0, params.aoa_sigma_px, 2) if params.aoa_sigma_px > 0 else np.zeros(2)
        self.s2 = math.log1p(params.scint_index)  # variance of ln I

    def step(self) -> tuple[np.ndarray, float, float]:
        """Advance one frame → (AoA offset px, intensity factor, extra PSF sigma px)."""
        p = self.p
        if p.aoa_sigma_px > 0:
            self.aoa = self.a * self.aoa + math.sqrt(1 - self.a ** 2) * self.rng.normal(
                0, p.aoa_sigma_px, 2)
        scint = 1.0
        if self.s2 > 0:
            scint = math.exp(self.rng.normal(-self.s2 / 2, math.sqrt(self.s2)))
        return self.aoa.copy(), scint, p.psf_broadening_px


class Platform:
    """Platform line-of-sight motion with peak rate ``rate`` px/frame and excursion ``amp``."""

    def __init__(self, kind: str, rate: float, amp: float, rng: np.random.Generator):
        self.kind, self.r, self.A, self.rng = kind, rate, max(amp, 1e-6), rng
        self.dir = np.array([math.cos(math.radians(30)), math.sin(math.radians(30))])
        self.p = np.zeros(2)
        self.v = np.zeros(2)
        self.th = 0.0

    def step(self, k: int) -> np.ndarray:
        """Offset (px) of the line of sight at frame ``k`` (call sequentially)."""
        if self.kind == "none" or self.r <= 0:
            return np.zeros(2)
        r, A = self.r, self.A
        if self.kind == "linear":
            return self.dir * fold(r * k, -A, A)
        if self.kind == "circular":
            w = r / A
            return A * np.array([math.cos(w * k), math.sin(w * k)])
        if self.kind == "figure8":
            p = np.array([A * math.sin(self.th), 0.5 * A * math.sin(2 * self.th)])
            self.th += r / max(math.hypot(A * math.cos(self.th), A * math.cos(2 * self.th)), 1e-6)
            return p
        if self.kind == "spiral":
            rad = A * tri(self.th / (8 * math.pi))
            p = rad * np.array([math.cos(self.th), math.sin(self.th)])
            self.th += r / math.hypot(max(rad, r), A / (4 * math.pi))
            return p
        if self.kind == "random":
            out = self.p.copy()
            self.v = np.clip(self.v + self.rng.normal(0, r / 4, 2), -r, r)
            self.p = self.p + self.v
            for i in range(2):
                if abs(self.p[i]) > A:
                    self.p[i] = math.copysign(2 * A - abs(self.p[i]), self.p[i])
                    self.v[i] = -self.v[i]
            return out
        raise ValueError(self.kind)


class Jitter:
    """White camera jitter, ±J px per frame per axis."""

    def __init__(self, amp: float, dist: str, rng: np.random.Generator):
        self.J, self.dist, self.rng = amp, dist, rng

    def step(self) -> np.ndarray:
        """Jitter offset (px) for the next frame."""
        if self.J <= 0:
            return np.zeros(2)
        if self.dist == "gaussian":
            return np.clip(self.rng.normal(0, self.J / 3, 2), -self.J, self.J)
        return self.rng.uniform(-self.J, self.J, 2)


@dataclass
class AtmosphereParams:
    """Resolved atmosphere parameters."""

    transmission: float
    airlight: float
    brightness: float
    blur_sigma: float
    rain_streaks: int


def resolve_atmosphere(cfg: DisturbanceConfig) -> AtmosphereParams:
    """Preset plus optional user contrast / brightness overrides."""
    t, a, b, blur, rain = ATMOSPHERE_PRESETS[cfg.atmosphere]
    if cfg.contrast is not None:
        t = cfg.contrast
    if cfg.brightness is not None:
        b = cfg.brightness
    return AtmosphereParams(t, a, b, blur, rain)


def apply_atmosphere(img: np.ndarray, p: AtmosphereParams, rng: np.random.Generator,
                     scale: float = 1.0) -> np.ndarray:
    """Contrast loss (transmission + airlight), blur, rain streaks, brightness (float32)."""
    out = img
    if p.transmission < 1.0 or p.airlight > 0:
        out = out * p.transmission + p.airlight * (1.0 - p.transmission)
    if p.blur_sigma > 0:
        out = cv2.GaussianBlur(out, (0, 0), p.blur_sigma * scale if scale < 1 else p.blur_sigma)
    if p.rain_streaks > 0:
        out = _rain(out, p.rain_streaks, rng, scale)
    if p.brightness != 1.0:
        out = out * p.brightness
    return out


def _rain(img: np.ndarray, n: int, rng: np.random.Generator, scale: float) -> np.ndarray:
    h, w = img.shape[:2]
    layer = np.zeros((h, w), np.float32)
    xs = rng.uniform(0, w, n)
    ys = rng.uniform(0, h, n)
    lens = rng.uniform(12, 40, n) * scale
    angs = np.radians(rng.normal(100, 6, n))
    vals = rng.uniform(15, 45, n)
    for x, y, ln, a, v in zip(xs, ys, lens, angs, vals):
        x2, y2 = x + ln * math.cos(a), y + ln * math.sin(a)
        cv2.line(layer, (int(x), int(y)), (int(x2), int(y2)), float(v), 1, cv2.LINE_AA)
    if img.ndim == 3:
        layer = layer[..., None]
    return img + layer


POISSON_EXACT_BELOW = 20.0


def fast_normal(shape: tuple, rng: np.random.Generator) -> np.ndarray:
    """Standard-normal float32 image, ~5× faster than NumPy.

    OpenCV's ``randn`` is seeded from ``rng`` on every call, so the result stays a
    deterministic function of the run seed (R4).
    """
    buf = np.empty(shape, np.float32)
    cv2.setRNGSeed(int(rng.integers(0, 2 ** 31 - 1)))
    cv2.randn(buf, 0.0, 1.0)
    return buf


def poisson_noise(img: np.ndarray, gain: float, rng: np.random.Generator) -> np.ndarray:
    """Shot noise: DN = gain · Poisson(DN / gain).

    Exact Poisson sampling for λ < 20 photo-electrons; above that the Gaussian limit
    N(λ, λ) is used (mean and variance exact; skewness 1/√λ ≤ 0.22 neglected), ~10× faster.
    """
    lam = img / gain
    out = lam + np.sqrt(lam) * fast_normal(lam.shape, rng)
    low = lam < POISSON_EXACT_BELOW
    if low.any():
        out[low] = rng.poisson(lam[low])
    return out.astype(np.float32) * gain


def apply_noise(img: np.ndarray, cfg: DisturbanceConfig, rng: np.random.Generator) -> np.ndarray:
    """Poisson → Gaussian → salt & pepper → 8-bit quantisation. Returns uint8.

    When every pixel is in the Gaussian limit of the Poisson distribution (λ ≥ 20
    photo-electrons), shot noise and read noise are independent Gaussians and are drawn as
    one normal variate with the summed variance (same distribution, half the cost).
    """
    out = np.clip(img, 0, None).astype(np.float32, copy=False)
    sig_g = cfg.gaussian_sigma if (cfg.gaussian and cfg.gaussian_sigma > 0) else 0.0
    if cfg.poisson and float(out.min()) / cfg.poisson_gain >= POISSON_EXACT_BELOW:
        std = np.sqrt(out * np.float32(cfg.poisson_gain) + np.float32(sig_g * sig_g))
        out = out + std * fast_normal(out.shape, rng)
    else:
        if cfg.poisson:
            out = poisson_noise(out, cfg.poisson_gain, rng)
        if sig_g > 0:
            out = out + fast_normal(out.shape, rng) * np.float32(sig_g)
    np.clip(out, 0, 255, out=out)
    q = np.rint(out, out=out).astype(np.uint8)
    if cfg.salt_pepper and cfg.sp_fraction > 0:
        r = rng.random(q.shape[:2], dtype=np.float32)
        half = cfg.sp_fraction / 2
        q[r < half] = 0
        q[(r >= half) & (r < cfg.sp_fraction)] = 255
    return q
