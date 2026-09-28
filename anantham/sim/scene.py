"""Virtual world and image rendering (GROUND TRUTH lives here).

The screen is an angular grid of ``screen_w × screen_h`` px (nominal IFOV). Beacons are
boxes convolved with a Gaussian PSF, integrated analytically over each pixel with the
error function, so their positions are truly sub-pixel. The background is a gentle
gradient plus a faint star field (clutter). Nothing in this module may be imported by
perception, tracking or control (enforced by ``tests/test_boundary.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.special import ndtr

from ..config.schema import Config, distractor_configs
from ..geometry import CameraGeometry
from .disturbances import (
    Jitter,
    Platform,
    Turbulence,
    apply_atmosphere,
    apply_noise,
    resolve_atmosphere,
    resolve_turbulence,
)
from .trajectories import TrajectorySpec, make_trajectory

_SQ2PI = math.sqrt(2 * math.pi)

# ---------------------------------------------------------------------------
# Analytic sub-pixel rendering
# ---------------------------------------------------------------------------


def _psi(z: np.ndarray) -> np.ndarray:
    """Antiderivative of the standard normal CDF: ∫Φ = zΦ(z) + φ(z)."""
    return z * ndtr(z) + np.exp(-0.5 * z * z) / _SQ2PI


def box_profile(edges: np.ndarray, centre: float, width: float, sigma: float) -> np.ndarray:
    """Pixel-integrated 1-D profile of a unit box (width) ⊗ Gaussian(sigma).

    ``edges`` are the pixel boundaries (n+1 values); returns n values in [0, 1].
    """
    sigma = max(sigma, 1e-3)
    a, b = centre - width / 2, centre + width / 2
    g = sigma * (_psi((edges - a) / sigma) - _psi((edges - b) / sigma))
    return np.diff(g)


def gauss_profile(edges: np.ndarray, centre: float, sigma: float) -> np.ndarray:
    """Pixel-integrated 1-D Gaussian with unit peak density scaling (peak ≈ 1)."""
    sigma = max(sigma, 1e-3)
    return np.diff(ndtr((edges - centre) / sigma)) * (_SQ2PI * sigma)


def render_spot(img: np.ndarray, x: float, y: float, amp: float, shape: str, w: float,
                h: float, sigma: float) -> None:
    """Add a beacon spot centred at image position (x, y) to ``img`` (float32, in place).

    Pixel centres are at ``i + 0.5``. ``w``/``h`` are the spot size in px (``h`` used
    for rectangles), ``sigma`` the total PSF sigma, ``amp`` the plateau level (DN).
    """
    if amp == 0:
        return
    H, W = img.shape[:2]
    half = 0.5 * max(w, h) + 4 * sigma + 2
    if shape == "gaussian":
        half = 4.5 * math.hypot(w / 2.3548, sigma) + 2
    x0, x1 = max(int(math.floor(x - half)), 0), min(int(math.ceil(x + half)), W)
    y0, y1 = max(int(math.floor(y - half)), 0), min(int(math.ceil(y + half)), H)
    if x0 >= x1 or y0 >= y1:
        return
    ex = np.arange(x0, x1 + 1, dtype=np.float64)
    ey = np.arange(y0, y1 + 1, dtype=np.float64)
    if shape in ("square", "rectangle"):
        hh = w if shape == "square" else h
        patch = np.outer(box_profile(ey, y, hh, sigma), box_profile(ex, x, w, sigma))
    elif shape == "gaussian":
        s = math.hypot(w / 2.3548, sigma)
        patch = np.outer(gauss_profile(ey, y, s), gauss_profile(ex, x, s))
    elif shape == "circle":
        patch = _circle_patch(x - x0, y - y0, x1 - x0, y1 - y0, w / 2, sigma)
    else:
        raise ValueError(f"unknown shape '{shape}'")
    if img.ndim == 3:
        img[y0:y1, x0:x1] += (amp * patch).astype(np.float32)[..., None]
    else:
        img[y0:y1, x0:x1] += (amp * patch).astype(np.float32)


def render_spot_moffat(img: np.ndarray, x: float, y: float, amp: float, shape: str, w: float,
                       h: float, sigma: float, beta: float = 3.0, ellip: float = 0.15) -> None:
    """Spot with a *different* optical model (Moffat, slightly elliptical, 8× supersampled).

    Used for evaluator-style test videos so that the renderer and the centroid model do
    not share one model (lesson 12h) — the reported centroid errors are then credible.
    """
    H, W = img.shape[:2]
    ss = 8
    fwhm = 2.3548 * sigma * 1.3
    alpha = fwhm / (2 * math.sqrt(2 ** (1 / beta) - 1))
    half = 0.5 * max(w, h) + 5 * fwhm + 2
    x0, x1 = max(int(math.floor(x - half)), 0), min(int(math.ceil(x + half)), W)
    y0, y1 = max(int(math.floor(y - half)), 0), min(int(math.ceil(y + half)), H)
    if x0 >= x1 or y0 >= y1:
        return
    ex = x0 + np.arange((x1 - x0) * ss + 1) / ss
    ey = y0 + np.arange((y1 - y0) * ss + 1) / ss
    hh = w if shape != "rectangle" else h
    fine = np.outer(box_profile(ey, y, hh, 0.01), box_profile(ex, x, w, 0.01)) * ss * ss
    r = int(math.ceil(3 * fwhm * ss))
    k = np.arange(-r, r + 1) / ss
    kx, ky = np.meshgrid(k, k * (1 + ellip))
    ker = (1 + (kx ** 2 + ky ** 2) / alpha ** 2) ** (-beta)
    ker = (ker / ker.sum()).astype(np.float32)
    fine = cv2.filter2D(fine.astype(np.float32), -1, ker, borderType=cv2.BORDER_CONSTANT)
    patch = fine.reshape(y1 - y0, ss, x1 - x0, ss).mean(axis=(1, 3))
    if img.ndim == 3:
        img[y0:y1, x0:x1] += (amp * patch)[..., None]
    else:
        img[y0:y1, x0:x1] += amp * patch


def _circle_patch(cx: float, cy: float, w: int, h: int, r: float, sigma: float) -> np.ndarray:
    ss = 5
    xs = (np.arange(w * ss) + 0.5) / ss
    ys = (np.arange(h * ss) + 0.5) / ss
    inside = ((xs[None, :] - cx) ** 2 + (ys[:, None] - cy) ** 2) <= r * r
    cov = inside.reshape(h, ss, w, ss).mean(axis=(1, 3)).astype(np.float32)
    if sigma > 0.05:
        cov = cv2.GaussianBlur(cov, (0, 0), sigma, borderType=cv2.BORDER_CONSTANT)
    return cov


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


@dataclass
class Beacon:
    """A beacon in the world (designated or distractor)."""

    traj: object
    size: float
    size_h: float
    shape: str
    amp: float
    psf: float
    blink_freq: float
    blink_dim: float
    blink_duty: float
    turb: Turbulence
    designated: bool
    occlusions: list = field(default_factory=list)
    present: bool = True

    def intensity_factor(self, t: float) -> float:
        """Blink and occlusion modulation at time ``t``."""
        if not self.present:
            return 0.0
        for start, dur in self.occlusions:
            if start <= t < start + dur:
                return 0.0
        if self.blink_freq > 0:
            return 1.0 if (t * self.blink_freq) % 1.0 < self.blink_duty else self.blink_dim
        return 1.0


@dataclass
class FrameState:
    """Per-frame disturbance + world state (ground truth)."""

    k: int
    t: float
    los: np.ndarray            # platform + jitter (px)
    platform: np.ndarray
    jitter: np.ndarray
    beacons: list              # list of dicts: u, v, aoa, scint, psf_extra, factor


class Scene:
    """World model: beacons, clutter, disturbances, renderer."""

    def __init__(self, cfg: Config, seed: int, box: tuple | None = None,
                 psf_model: str = "gaussian"):
        self.cfg = cfg
        self.psf_model = psf_model
        cam, tgt, dist = cfg.camera, cfg.target, cfg.disturbances
        self.geom = CameraGeometry(cam.res_w, cam.res_h, cam.fov_h_deg, cam.fov_v_deg)
        self.fps = cam.fps
        ss = np.random.SeedSequence(seed)
        (r_traj, r_dis, r_star, r_turb, r_plat, r_jit, self.rng_noise,
         self.rng_atm, r_wide) = [np.random.default_rng(s) for s in ss.spawn(9)]
        self.rng_wide = r_wide
        self.box = box if box is not None else self._box()
        self.turb_params = resolve_turbulence(dist.turbulence)
        self.atm = resolve_atmosphere(dist)
        v_px = self._speed_px(tgt.speed_deg_s)
        start = self._start(r_traj)
        self.beacons: list[Beacon] = [Beacon(
            traj=make_trajectory(TrajectorySpec(tgt.motion, v_px, tgt.radius_px, self.box, start,
                                                tgt.waypoints, cam.fps), r_traj),
            size=tgt.size_px, size_h=tgt.size_h_px, shape=tgt.shape, amp=tgt.intensity_dn,
            psf=tgt.psf_sigma_px,
            blink_freq=tgt.blink.freq_hz if tgt.blink.enabled else 0.0,
            blink_dim=tgt.blink.dim_factor, blink_duty=tgt.blink.duty,
            turb=Turbulence(self.turb_params, cam.fps, r_turb), designated=True,
            occlusions=[tuple(o) for o in tgt.occlusions], present=tgt.present)]
        for d in distractor_configs(cfg):
            rng = np.random.default_rng(r_dis.integers(0, 2 ** 63))
            st = None if d.start_x_px is None else np.array([d.start_x_px, d.start_y_px])
            self.beacons.append(Beacon(
                traj=make_trajectory(TrajectorySpec(d.motion, self._speed_px(d.speed_deg_s),
                                                    tgt.radius_px, self.box, st, [], cam.fps),
                                     rng),
                size=d.size_px, size_h=d.size_px, shape=tgt.shape, amp=d.intensity_dn,
                psf=tgt.psf_sigma_px, blink_freq=d.blink_freq_hz,
                blink_dim=tgt.blink.dim_factor, blink_duty=tgt.blink.duty,
                turb=Turbulence(self.turb_params, cam.fps, rng), designated=False))
        self.platform = Platform(dist.platform, dist.platform_rate_px,
                                 dist.platform_amplitude_px, r_plat)
        self.jitter = Jitter(dist.jitter_px, dist.jitter_dist, r_jit)
        self.stars = self._make_stars(r_star)
        self.state: FrameState | None = None

    # --- construction helpers ----------------------------------------------------
    def _speed_px(self, deg_s: float) -> float:
        return deg_s / self.fps / self.geom.ifov_h_deg

    def margin(self) -> tuple[float, float]:
        """Trajectory margin (x, y) in screen px: half FOV + 20 px unless configured."""
        m = self.cfg.target.margin_px
        if m is not None:
            return m, m
        return self.cfg.camera.res_w / 2 + 20, self.cfg.camera.res_h / 2 + 20

    def _box(self) -> tuple[float, float, float, float]:
        mx, my = self.margin()
        sw, sh = self.cfg.camera.screen_w_px, self.cfg.camera.screen_h_px
        mx, my = min(mx, sw / 2 - 1), min(my, sh / 2 - 1)
        return (mx, my, sw - mx, sh - my)

    def _start(self, rng: np.random.Generator) -> np.ndarray | None:
        tgt, cam = self.cfg.target, self.cfg.camera
        c = np.array([cam.screen_w_px / 2 + cam.initial_pan_deg / self.geom.ifov_h_deg,
                      cam.screen_h_px / 2 + cam.initial_tilt_deg / self.geom.ifov_v_deg])
        if tgt.start == "user":
            return np.array([tgt.start_x_px, tgt.start_y_px], float)
        if tgt.start == "centre":
            return c
        if tgt.start == "in_fov":
            return c + rng.uniform(-0.3, 0.3, 2) * np.array([cam.res_w, cam.res_h])
        return None

    def _make_stars(self, rng: np.random.Generator) -> np.ndarray:
        cam = self.cfg.camera
        n = int(round(cam.star_density * cam.screen_w_px * cam.screen_h_px / 1e4))
        if n == 0:
            return np.zeros((0, 4))
        u = rng.uniform(0, cam.screen_w_px, n)
        v = rng.uniform(0, cam.screen_h_px, n)
        amp = np.clip(rng.lognormal(math.log(22), 0.45, n), 8, 90)
        sig = rng.uniform(0.55, 0.9, n)
        return np.stack([u, v, amp, sig], axis=1)

    # --- per-frame ------------------------------------------------------------------
    def advance(self, k: int) -> FrameState:
        """Compute the ground-truth world state of frame ``k`` (call sequentially)."""
        if self.state is not None and k != self.state.k + 1:
            raise RuntimeError("Scene.advance must be called with consecutive frames")
        t = k / self.fps
        plat = self.platform.step(k)
        jit = self.jitter.step()
        beacons = []
        for b in self.beacons:
            p = b.traj.position(k)
            aoa, scint, psf_extra = b.turb.step()
            beacons.append({"u": float(p[0]), "v": float(p[1]), "aoa": aoa, "scint": scint,
                            "psf_extra": psf_extra, "factor": b.intensity_factor(t),
                            "on_screen": self.on_screen(p[0], p[1])})
        self.state = FrameState(k, t, plat + jit, plat, jit, beacons)
        return self.state

    def on_screen(self, u: float, v: float) -> bool:
        """Is a screen position inside the physical screen?"""
        cam = self.cfg.camera
        return 0.0 <= u < cam.screen_w_px and 0.0 <= v < cam.screen_h_px

    def _background(self, us: np.ndarray, vs: np.ndarray) -> np.ndarray:
        cam = self.cfg.camera
        b0 = cam.background_dn
        gx = b0 * 0.3 * (us / cam.screen_w_px - 0.5)
        gy = b0 * 0.2 * (vs / cam.screen_h_px - 0.5)
        sx = np.sin(2 * np.pi * us / 700.0 + 0.5)
        cy = np.cos(2 * np.pi * vs / 900.0)
        bg = b0 + gy[:, None] + gx[None, :] + 0.08 * b0 * (cy[:, None] * sx[None, :])
        return bg.astype(np.float32)

    def render(self, bore_u: float, bore_v: float) -> tuple[np.ndarray, dict]:
        """Render the narrow camera image for the current state → (image, truth)."""
        st, g, cam = self.state, self.geom, self.cfg.camera
        W, H = cam.res_w, cam.res_h
        los = st.los
        us = bore_u + (np.arange(W) + 0.5 - g.cx) - los[0]
        vs = bore_v + (np.arange(H) + 0.5 - g.cy) - los[1]
        bg = self._background(us, vs)
        stars = self.stars
        if len(stars):
            sel = ((np.abs(stars[:, 0] - bore_u) < W / 2 + 60) &
                   (np.abs(stars[:, 1] - bore_v) < H / 2 + 60))
            for u, v, a, s in stars[sel]:
                x, y = g.pointing_to_image(u, v, bore_u, bore_v)
                render_spot(bg, x + los[0], y + los[1], a, "gaussian", 0.0, 0.0, s)
        sig = np.zeros((H, W), np.float32)
        truth = {"k": st.k, "t": st.t, "platform": st.platform.tolist(),
                 "jitter": st.jitter.tolist(), "beacons": []}
        for b, bs in zip(self.beacons, st.beacons):
            gx, gy = g.pointing_to_image(bs["u"], bs["v"], bore_u, bore_v)
            gx, gy = gx + los[0], gy + los[1]
            ax, ay = gx + bs["aoa"][0], gy + bs["aoa"][1]
            visible = bs["on_screen"] and bs["factor"] > 0
            if visible:
                draw = render_spot_moffat if self.psf_model == "moffat" else render_spot
                draw(sig, ax, ay, b.amp * bs["factor"] * bs["scint"], b.shape, b.size,
                     b.size_h, math.hypot(b.psf, bs["psf_extra"]))
            truth["beacons"].append({
                "designated": b.designated, "screen_u": bs["u"], "screen_v": bs["v"],
                "app_x": ax, "app_y": ay, "geo_x": gx, "geo_y": gy,
                "ctrl_x": gx - st.jitter[0], "ctrl_y": gy - st.jitter[1],
                "visible": bool(visible), "factor": bs["factor"],
                "in_fov": bool(visible and 0 <= ax < W and 0 <= ay < H)})
        img = self._finish(bg, sig, self.rng_noise, 1.0)
        return img, truth

    def render_wide(self) -> tuple[np.ndarray, float]:
        """Render the OPTIONAL wide-FOV acquisition sensor (whole screen at 1/N)."""
        st, cam = self.state, self.cfg.camera
        n = self.cfg.acquisition.wide_downscale
        W, H = int(math.ceil(cam.screen_w_px / n)), int(math.ceil(cam.screen_h_px / n))
        los = st.los / n
        us = (np.arange(W) + 0.5) * n - st.los[0]
        vs = (np.arange(H) + 0.5) * n - st.los[1]
        bg = self._background(us, vs)
        for u, v, a, _s in self.stars:
            render_spot(bg, u / n + los[0], v / n + los[1], a, "gaussian", 0.0, 0.0, 0.6)
        sig = np.zeros((H, W), np.float32)
        for b, bs in zip(self.beacons, st.beacons):
            if bs["on_screen"] and bs["factor"] > 0:
                x = (bs["u"] + st.los[0] + bs["aoa"][0]) / n
                y = (bs["v"] + st.los[1] + bs["aoa"][1]) / n
                render_spot(sig, x, y, b.amp * bs["factor"] * bs["scint"], b.shape, b.size / n,
                            b.size_h / n, max(math.hypot(b.psf, bs["psf_extra"]) / n, 0.6))
        return self._finish(bg, sig, self.rng_wide, 1.0 / n), float(n)

    def _finish(self, bg: np.ndarray, sig: np.ndarray, rng: np.random.Generator,
                scale: float) -> np.ndarray:
        if self.cfg.camera.color:
            img = (bg[..., None] * np.array([1.08, 1.0, 0.9], np.float32) +
                   sig[..., None] * np.array([0.55, 0.85, 1.0], np.float32))
        else:
            img = bg + sig
        img = apply_atmosphere(img, self.atm, self.rng_atm, scale)
        return apply_noise(img, self.cfg.disturbances, rng)
