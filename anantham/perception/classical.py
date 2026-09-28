"""Classical beacon detector.

Pipeline (section 4.3): 3×3 median → morphological top-hat (kernel ≈ 2.5·s + 4) →
zero a border → robust threshold (median + k·MAD) → 8-connected components →
features (area, peak, flux, fill, SNR, edge flag) → signature score
(size match × compactness × brightness) → intensity-weighted sub-pixel centroid
(pixel centres at ``i + 0.5``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config.schema import PerceptionConfig


@dataclass
class Candidate:
    """A detected blob with its features (image coordinates, px)."""

    x: float
    y: float
    area: int
    peak: float
    flux: float
    fill: float
    snr: float
    size_est: float
    size_match: float
    compactness: float
    brightness: float
    score: float
    edge: bool
    bbox: tuple[int, int, int, int]
    cnn_prob: float | None = None
    accepted: bool = True
    reason: str = ""
    u: float = float("nan")  # pointing-frame position (filled by the PAT loop)
    v: float = float("nan")

    def as_row(self) -> dict:
        """Compact dict for tables / logs."""
        return {"x": round(self.x, 2), "y": round(self.y, 2), "score": round(self.score, 3),
                "size_match": round(self.size_match, 3), "snr": round(self.snr, 1),
                "cnn": None if self.cnn_prob is None else round(self.cnn_prob, 3),
                "edge": self.edge, "accepted": self.accepted, "reason": self.reason}


@dataclass
class PerceptionResult:
    """Output of one detector call."""

    candidates: list[Candidate]
    noise_sigma: float
    threshold: float
    debug: dict = field(default_factory=dict)


def size_match(est: float, expected: float, tol: float) -> float:
    """Log-normal size agreement in [0, 1] (1 = identical size)."""
    if est <= 0 or expected <= 0:
        return 0.0
    d = math.log(est / expected)
    return math.exp(-0.5 * (d / tol) ** 2)


def equivalent_size(shape: str, w: float, h: float) -> float:
    """sqrt(half-max area) expected for a spot of the given shape and size."""
    if shape == "circle":
        return w * math.sqrt(math.pi) / 2
    if shape == "gaussian":
        return w * math.sqrt(math.pi) / 2
    if shape == "rectangle":
        return math.sqrt(w * h)
    return w


class ClassicalDetector:
    """Median / top-hat / robust-threshold / components / signature detector."""

    def __init__(self, cfg: PerceptionConfig, expected_size: float):
        self.cfg = cfg
        self.set_scale(expected_size)

    def set_scale(self, expected_size: float) -> None:
        """Derive the top-hat kernel and windows from the expected spot size (px)."""
        self.s = float(max(expected_size, 1.0))
        k = int(round(self.cfg.tophat_factor * self.s + self.cfg.tophat_add))
        k += (k + 1) % 2
        self.kernel_size = max(k, 5)
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                                (self.kernel_size, self.kernel_size))
        self.max_area = int((3.0 * self.s + 8) ** 2)

    # ------------------------------------------------------------------------------
    def detect(self, gray: np.ndarray, debug: bool = False) -> PerceptionResult:
        """Detect beacon candidates in a uint8 grey image."""
        med = cv2.medianBlur(gray, 3)
        top = cv2.morphologyEx(med, cv2.MORPH_TOPHAT, self.kernel)
        b = self.cfg.border_px
        if b > 0:
            top[:b, :] = 0
            top[-b:, :] = 0
            top[:, :b] = 0
            top[:, -b:] = 0
        sub = top[b:-b:3, b:-b:3] if b > 0 else top[::3, ::3]
        m = float(np.median(sub))
        mad = float(np.median(np.abs(sub.astype(np.float32) - m)))
        sigma = max(1.4826 * mad, self.cfg.min_noise_dn)
        thr = m + self.cfg.k_mad * sigma
        mask = (top > thr).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        cands: list[Candidate] = []
        if n > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            idx = np.nonzero((areas >= 2) & (areas <= self.max_area))[0] + 1
            if len(idx):
                sel = mask.astype(bool)
                allpk = np.zeros(n, np.float32)
                np.maximum.at(allpk, labels[sel], top[sel].astype(np.float32))
                peaks = allpk[idx]
                order = np.argsort(-(peaks * np.sqrt(stats[idx, cv2.CC_STAT_AREA])))
                idx = idx[order[: 2 * self.cfg.max_candidates]]
                topf = top.astype(np.float32)
                for lab in idx:
                    c = self._features(topf, stats[lab], m, sigma, thr, gray.shape)
                    if c is not None:
                        cands.append(c)
        cands.sort(key=lambda c: -c.score)
        cands = cands[: self.cfg.max_candidates]
        dbg = {"median": med, "tophat": top, "mask": mask * 255} if debug else {}
        return PerceptionResult(cands, sigma, thr, dbg)

    def _features(self, top: np.ndarray, st: np.ndarray, bg: float, sigma: float, thr: float,
                  shape: tuple) -> Candidate | None:
        H, W = shape[:2]
        x, y, w, h, area = (int(v) for v in st[:5])
        pad = 2
        x0, y0 = max(x - pad, 0), max(y - pad, 0)
        x1, y1 = min(x + w + pad, W), min(y + h + pad, H)
        win = top[y0:y1, x0:x1] - bg
        flat = np.sort(win, axis=None)
        peak = float(flat[-3:].mean()) if flat.size >= 3 else float(flat[-1])
        if peak <= 0:
            return None
        hm = win >= 0.5 * peak
        a_hm = int(hm.sum())
        ys, xs = np.nonzero(hm)
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        fill = a_hm / float(bw * bh)
        aspect = min(bw, bh) / float(max(bw, bh))
        size_est = math.sqrt(a_hm)
        sm = size_match(size_est, self.s, self.cfg.size_tolerance)
        compact = math.sqrt(min(fill / 0.7, 1.0) * aspect)
        snr = peak / sigma
        bright = 1.0 - math.exp(-snr / 8.0)
        wts = np.clip(win - (thr - bg), 0, None)
        tot = float(wts.sum())
        if tot <= 0:
            return None
        gx = np.arange(x0, x1, dtype=np.float32) + 0.5
        gy = np.arange(y0, y1, dtype=np.float32) + 0.5
        cx = float((wts.sum(axis=0) * gx).sum() / tot)
        cy = float((wts.sum(axis=1) * gy).sum() / tot)
        b = self.cfg.border_px + 1
        edge = x <= b or y <= b or x + w >= W - b or y + h >= H - b
        return Candidate(cx, cy, area, peak, tot, fill, snr, size_est, sm, compact, bright,
                         sm * compact * bright, edge, (x, y, w, h))


def centroid_moment(img: np.ndarray, bg: float = 0.0) -> tuple[float, float]:
    """Plain intensity-weighted centroid of ``img - bg`` (pixel centres at i + 0.5)."""
    w = np.clip(img.astype(np.float64) - bg, 0, None)
    tot = w.sum()
    ys, xs = np.indices(w.shape)
    return float(((xs + 0.5) * w).sum() / tot), float(((ys + 0.5) * w).sum() / tot)
