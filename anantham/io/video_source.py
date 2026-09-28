"""Evaluator MP4 input: bypasses the PTZ camera and feeds external video to the PAT stack.

Any resolution and frame rate is accepted; colour frames are converted to grey. The
camera is fixed, so the boresight is *virtual*: rate commands move a virtual boresight
inside the image with the configured pan/tilt slew limits (converted to px/frame via the
user-supplied FOV). An optional truth CSV (``frame,time_s,x_px,y_px[,visible]``,
pixel-centre convention) enables centroiding / virtual pointing error metrics.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import cv2
import numpy as np

from ..config.schema import Config
from ..geometry import CameraGeometry
from .base import Frame, FrameSource


def load_truth_csv(path: str | Path) -> dict[int, dict]:
    """Read a truth CSV into ``{frame: {x, y, visible}}``."""
    out: dict[int, dict] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            vis = row.get("visible", "1")
            x, y = row.get("x_px", ""), row.get("y_px", "")
            ok = vis not in ("0", "false", "False") and x not in ("", "nan") and y not in ("", "nan")
            out[int(row["frame"])] = {"x": float(x) if ok else float("nan"),
                                      "y": float(y) if ok else float("nan"), "visible": ok}
    return out


class VideoSource(FrameSource):
    """MP4 / AVI file source with a virtual boresight."""

    los_moves_with_command = False
    screen_px = None

    def __init__(self, path: str | Path, cfg: Config, truth_csv: str | Path | None = None):
        self.path = str(path)
        self.cap = cv2.VideoCapture(self.path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"cannot open video '{path}'")
        self.cfg = cfg
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = float(fps) if fps and fps > 1 else cfg.camera.fps
        self._count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
        fov_h = cfg.camera.fov_h_deg
        self.geometry = CameraGeometry(self.width, self.height, fov_h,
                                       fov_h * self.height / self.width)
        self.bore = [self.geometry.cx, self.geometry.cy]
        self.k = -1
        self.truth_rows = load_truth_csv(truth_csv) if truth_csv else None
        self._truth: dict | None = None

    @property
    def n_frames(self) -> int | None:
        """Frame count reported by the container (may be approximate)."""
        return self._count

    @staticmethod
    def to_grey(img: np.ndarray) -> np.ndarray:
        """Convert any decoded frame to uint8 grey."""
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if img.dtype != np.uint8:
            img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return img

    def peek(self, n: int) -> list[np.ndarray]:
        """Read the first ``n`` grey frames without consuming them."""
        cap = cv2.VideoCapture(self.path)
        frames = []
        for _ in range(n):
            ok, img = cap.read()
            if not ok:
                break
            frames.append(self.to_grey(img))
        cap.release()
        return frames

    def read(self) -> Frame | None:
        """Decode the next frame."""
        t0 = time.perf_counter()
        ok, img = self.cap.read()
        if not ok:
            return None
        self.k += 1
        grey = self.to_grey(img)
        self._truth = self._make_truth()
        return Frame(self.k, self.k / self.fps, grey, (self.bore[0], self.bore[1]),
                     ((self.bore[0] - self.geometry.cx) * self.geometry.ifov_h_deg,
                      (self.bore[1] - self.geometry.cy) * self.geometry.ifov_v_deg),
                     None, 1.0, (time.perf_counter() - t0) * 1e3)

    def _make_truth(self) -> dict | None:
        if self.truth_rows is None:
            return None
        row = self.truth_rows.get(self.k)
        vis = bool(row and row["visible"])
        x, y = (row["x"], row["y"]) if vis else (float("nan"), float("nan"))
        b = {"designated": True, "app_x": x, "app_y": y, "geo_x": x, "geo_y": y,
             "ctrl_x": x, "ctrl_y": y, "visible": vis,
             "in_fov": vis and 0 <= x < self.width and 0 <= y < self.height}
        return {"k": self.k, "t": self.k / self.fps, "beacons": [b],
                "bore_img": [self.bore[0], self.bore[1]]}

    def command(self, pan_rate_deg_s: float, tilt_rate_deg_s: float) -> tuple[float, float]:
        """Move the virtual boresight with the configured slew limits."""
        c = self.cfg.camera
        pr = min(max(pan_rate_deg_s, -c.max_pan_rate_deg_s), c.max_pan_rate_deg_s)
        tr = min(max(tilt_rate_deg_s, -c.max_tilt_rate_deg_s), c.max_tilt_rate_deg_s)
        g = self.geometry
        self.bore[0] = min(max(self.bore[0] + g.rate_deg_s_to_px_frame(pr, self.fps, "h"), 0),
                           self.width)
        self.bore[1] = min(max(self.bore[1] + g.rate_deg_s_to_px_frame(tr, self.fps, "v"), 0),
                           self.height)
        return pr, tr

    def truth(self) -> dict | None:
        """Truth row of the last frame (if a truth CSV was supplied)."""
        return self._truth

    def close(self) -> None:
        """Release the decoder."""
        self.cap.release()
