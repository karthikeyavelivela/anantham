"""CNN beacon verifier + heatmap centroid refinement (ONNX Runtime, CPU).

Network (trained in ``anantham/training``): a small fully convolutional net with two
heads, exported to ONNX:

* ``score``   — beacon / not-beacon logit for a 64×64 ROI centred on a candidate
* ``heatmap`` — stride-4 centre heatmap logits (16×16 for a 64×64 ROI)
* ``offset``  — stride-4 sub-cell offset (2 channels, in cells) for refinement

The verifier is optional (``perception.mode = classical`` switches it off) so its
effect can be measured in the ablation study.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

ROI = 64
STRIDE = 4
DEFAULT_MODEL = Path(__file__).resolve().parent.parent / "models" / "verifier.onnx"


def normalise_roi(roi: np.ndarray) -> np.ndarray:
    """Background-subtract and contrast-normalise a grey ROI to float32."""
    r = roi.astype(np.float32)
    bg = float(np.median(r))
    hi = float(np.percentile(r, 99.5))
    scale = max(hi - bg, 8.0)
    return np.clip((r - bg) / scale, -2.0, 4.0)


def extract_roi(gray: np.ndarray, x: float, y: float, side: int) -> tuple[np.ndarray, float, float]:
    """Crop a ``side``×``side`` ROI centred at (x, y) (reflect-padded) and resize to 64.

    Returns (roi64, x0, y0) where (x0, y0) is the ROI's top-left in image px.
    """
    H, W = gray.shape[:2]
    x0 = int(math.floor(x - side / 2 + 0.5))
    y0 = int(math.floor(y - side / 2 + 0.5))
    pad = side
    if x0 < 0 or y0 < 0 or x0 + side > W or y0 + side > H:
        g = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_REFLECT)
        crop = g[y0 + pad:y0 + pad + side, x0 + pad:x0 + pad + side]
    else:
        crop = gray[y0:y0 + side, x0:x0 + side]
    if side != ROI:
        crop = cv2.resize(crop, (ROI, ROI), interpolation=cv2.INTER_AREA)
    return crop, float(x0), float(y0)


def decode_heatmap(heat: np.ndarray, off: np.ndarray, centre_only: bool = True
                   ) -> tuple[float, float, float]:
    """Heatmap logits (h, w) + offsets (2, h, w) → (x, y, prob) in input px."""
    h, w = heat.shape
    if centre_only:
        c0, c1 = h // 2 - 3, h // 2 + 3
        sub = heat[c0:c1, c0:c1]
        iy, ix = np.unravel_index(int(np.argmax(sub)), sub.shape)
        iy, ix = iy + c0, ix + c0
    else:
        iy, ix = np.unravel_index(int(np.argmax(heat)), heat.shape)
    prob = 1.0 / (1.0 + math.exp(-float(heat[iy, ix])))
    x = (ix + float(off[0, iy, ix])) * STRIDE
    y = (iy + float(off[1, iy, ix])) * STRIDE
    return x, y, prob


class CnnVerifier:
    """ONNX Runtime wrapper for the ROI verifier / heatmap network."""

    def __init__(self, model_path: str | Path | None = None, threads: int = 1):
        import onnxruntime as ort

        path = Path(model_path) if model_path else DEFAULT_MODEL
        if not path.exists():
            raise FileNotFoundError(f"CNN model not found: {path} (run anantham train)")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.path = path

    def roi_side(self, spot_size: float) -> int:
        """ROI crop side so that the spot appears at a trained scale in 64 px."""
        return int(max(ROI, round(4.0 * spot_size)))

    def infer(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Run the net on a float32 batch (N, 1, H, W) → (score, heat, offset)."""
        score, heat, off = self.sess.run(None, {"input": batch})
        return score[:, 0], heat[:, 0], off

    def verify(self, gray: np.ndarray, points: list[tuple[float, float]], spot_size: float
               ) -> list[tuple[float, float, float]]:
        """For each (x, y): → (probability, refined_x, refined_y) in image px."""
        if not points:
            return []
        side = self.roi_side(spot_size)
        rois, origins = [], []
        for x, y in points:
            r, x0, y0 = extract_roi(gray, x, y, side)
            rois.append(normalise_roi(r))
            origins.append((x0, y0))
        batch = np.stack(rois)[:, None]
        score, heat, off = self.infer(batch)
        k = side / ROI
        out = []
        for i, (x0, y0) in enumerate(origins):
            p = 1.0 / (1.0 + math.exp(-float(score[i])))
            hx, hy, _ = decode_heatmap(heat[i], off[i])
            out.append((p, x0 + hx * k, y0 + hy * k))
        return out

    def detect_full(self, gray: np.ndarray, spot_size: float, thr: float = 0.5,
                    max_det: int = 10) -> list[tuple[float, float, float]]:
        """CNN-only detection: tile the frame into ROIs → [(x, y, prob)] peaks."""
        side = self.roi_side(spot_size)
        stride = side * 3 // 4
        H, W = gray.shape[:2]
        tiles, origins = [], []
        for y0 in range(-side // 8, H - side // 2, stride):
            for x0 in range(-side // 8, W - side // 2, stride):
                r, ox, oy = extract_roi(gray, x0 + side / 2, y0 + side / 2, side)
                tiles.append(normalise_roi(r))
                origins.append((ox, oy))
        score, heat, off = self.infer(np.stack(tiles)[:, None])
        k = side / ROI
        dets = []
        for i, (ox, oy) in enumerate(origins):
            hx, hy, p = decode_heatmap(heat[i], off[i], centre_only=False)
            if p < thr:
                continue
            x, y = ox + hx * k, oy + hy * k
            if all(math.hypot(x - d[0], y - d[1]) > spot_size for d in dets):
                dets.append((x, y, p))
            else:
                for j, d in enumerate(dets):
                    if math.hypot(x - d[0], y - d[1]) <= spot_size and p > d[2]:
                        dets[j] = (x, y, p)
        dets.sort(key=lambda d: -d[2])
        return dets[:max_det]
