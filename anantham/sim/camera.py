"""Virtual rate-limited pan/tilt camera (actuator model).

The camera keeps commanded pan/tilt angles. Commands are angular rates (deg/s); the
slew limiter clamps every command to the configured per-axis maximum, so the limit can
never be exceeded (unit-tested). An optional actuation delay of N frames is modelled
with a FIFO. Pan/tilt travel is limited so the boresight stays on the screen; the FOV
itself may extend beyond the screen edge and sees padded background (policy for
lesson 12e: every on-screen target position is reachable by the boresight).
"""

from __future__ import annotations

from collections import deque

from ..config.schema import CameraConfig
from ..geometry import CameraGeometry


class PanTiltCamera:
    """Pan/tilt state + slew limiter."""

    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.geom = CameraGeometry(cfg.res_w, cfg.res_h, cfg.fov_h_deg, cfg.fov_v_deg)
        self.dt = 1.0 / cfg.fps
        self.pan = float(cfg.initial_pan_deg)
        self.tilt = float(cfg.initial_tilt_deg)
        self.pan_limit = cfg.screen_w_px / 2 * self.geom.ifov_h_deg
        self.tilt_limit = cfg.screen_h_px / 2 * self.geom.ifov_v_deg
        self.rate = (0.0, 0.0)
        self._queue: deque[tuple[float, float]] = deque(
            [(0.0, 0.0)] * cfg.command_latency_frames)

    @property
    def boresight_px(self) -> tuple[float, float]:
        """Boresight position in screen (pointing-frame) px."""
        return (self.cfg.screen_w_px / 2 + self.pan / self.geom.ifov_h_deg,
                self.cfg.screen_h_px / 2 + self.tilt / self.geom.ifov_v_deg)

    def clamp_rate(self, pan_rate: float, tilt_rate: float) -> tuple[float, float]:
        """Clamp a rate command to the per-axis slew limits (deg/s)."""
        mp, mt = self.cfg.max_pan_rate_deg_s, self.cfg.max_tilt_rate_deg_s
        return (min(max(pan_rate, -mp), mp), min(max(tilt_rate, -mt), mt))

    def command(self, pan_rate: float, tilt_rate: float) -> tuple[float, float]:
        """Apply a rate command for one frame; returns the rate actually applied."""
        self._queue.append(self.clamp_rate(pan_rate, tilt_rate))
        pr, tr = self._queue.popleft()
        new_pan = min(max(self.pan + pr * self.dt, -self.pan_limit), self.pan_limit)
        new_tilt = min(max(self.tilt + tr * self.dt, -self.tilt_limit), self.tilt_limit)
        self.rate = ((new_pan - self.pan) / self.dt, (new_tilt - self.tilt) / self.dt)
        self.pan, self.tilt = new_pan, new_tilt
        return self.rate
