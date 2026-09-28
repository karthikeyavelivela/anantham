"""Simulator frame source: Scene + pan/tilt camera behind the FrameSource interface."""

from __future__ import annotations

import time

from ..config.schema import Config
from ..sim.camera import PanTiltCamera
from ..sim.scene import Scene
from .base import Frame, FrameSource


class SimSource(FrameSource):
    """Closed-loop simulated camera. Truth is available via :meth:`truth` only."""

    los_moves_with_command = True

    def __init__(self, cfg: Config, seed: int | None = None, duration_s: float | None = None):
        self.cfg = cfg
        self.seed = cfg.run.seed if seed is None else seed
        self.scene = Scene(cfg, self.seed)
        self.camera = PanTiltCamera(cfg.camera)
        self.geometry = self.camera.geom
        self.fps = cfg.camera.fps
        self.screen_px = (float(cfg.camera.screen_w_px), float(cfg.camera.screen_h_px))
        dur = cfg.run.duration_s if duration_s is None else duration_s
        self._n = None if dur is None or dur <= 0 else int(round(dur * self.fps))
        self.k = -1
        self._truth: dict | None = None
        self.wide_enabled = cfg.acquisition.mode == "wide_fov"

    @property
    def n_frames(self) -> int | None:
        """Number of frames in the run (None = unlimited)."""
        return self._n

    def read(self) -> Frame | None:
        """Advance the world one frame and render the camera view."""
        if self._n is not None and self.k + 1 >= self._n:
            return None
        t0 = time.perf_counter()
        self.k += 1
        self.scene.advance(self.k)
        bu, bv = self.camera.boresight_px
        img, truth = self.scene.render(bu, bv)
        wide, ws = (None, 1.0)
        if self.wide_enabled:
            wide, ws = self.scene.render_wide()
        truth["bore_img"] = [self.geometry.cx, self.geometry.cy]
        truth["bore_screen"] = [bu, bv]
        self._truth = truth
        return Frame(self.k, self.k / self.fps, img, (bu, bv),
                     (self.camera.pan, self.camera.tilt), wide, ws,
                     (time.perf_counter() - t0) * 1e3)

    def command(self, pan_rate_deg_s: float, tilt_rate_deg_s: float) -> tuple[float, float]:
        """Slew-limited rate command to the virtual pan/tilt unit."""
        return self.camera.command(pan_rate_deg_s, tilt_rate_deg_s)

    def truth(self) -> dict | None:
        """Ground truth of the last rendered frame."""
        return self._truth
