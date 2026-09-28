"""Pan/tilt rate controller (section 4.8).

Plant: pointing integrates the rate command, ``p[k+1] = p[k] + u[k]`` (px/frame).
Law (per axis, in pointing px):

    aim  = x̂ + v̂·L                       (latency compensation, L frames)
    e    = aim − p
    u    = g·(Kp·e + Kd·Δe) + Ki·∫e + ff·v̂
    g    = 1 / (1 + σ_KF/σ0)              (uncertainty-scaled gains)

With ff = 1 the steady-state error for a constant-velocity target is zero and the error
decays as (1 − g·Kp)^k. The integrator is frozen while the output saturates
(anti-windup) and the command is clamped to the per-axis slew limit.
"""

from __future__ import annotations

import numpy as np

from ..config.schema import ControlConfig


class PanTiltController:
    """PID + velocity feed-forward with anti-windup, deadband and slew clamps."""

    def __init__(self, cfg: ControlConfig, max_px_frame: tuple[float, float]):
        self.cfg = cfg
        self.umax = np.asarray(max_px_frame, float)
        self.reset()

    def reset(self) -> None:
        """Clear integrator and derivative memory."""
        self.integ = np.zeros(2)
        self.prev_e: np.ndarray | None = None
        self.saturated = np.zeros(2, bool)

    def track(self, pos: np.ndarray, vel: np.ndarray, bore: np.ndarray, sigma: float,
              use_ff: bool = True) -> np.ndarray:
        """Rate command (px/frame per axis) to keep ``pos`` on the boresight."""
        c = self.cfg
        v = np.asarray(vel, float) if c.feedforward and use_ff else np.zeros(2)
        aim = np.asarray(pos, float) + v * c.latency_frames
        e = aim - np.asarray(bore, float)
        e_p = np.where(np.abs(e) < c.deadband_px, 0.0, e)
        de = np.zeros(2) if self.prev_e is None else e - self.prev_e
        self.prev_e = e
        g = 1.0 / (1.0 + sigma / c.sigma0_px) if c.uncertainty_scaling else 1.0
        u_unsat = g * (c.kp * e_p + c.kd * de) + c.ki * self.integ + c.ff_gain * v
        u = np.clip(u_unsat, -self.umax, self.umax)
        self.saturated = np.abs(u_unsat) > self.umax
        # anti-windup: integrate only on unsaturated axes
        self.integ = np.where(self.saturated, self.integ,
                              np.clip(self.integ + e_p, -c.integral_limit_px, c.integral_limit_px))
        return u

    def slew_to(self, target: np.ndarray, bore: np.ndarray) -> np.ndarray:
        """Maximum-rate move towards ``target`` (search patterns); resets the PID."""
        self.reset()
        return np.clip(np.asarray(target, float) - np.asarray(bore, float), -self.umax, self.umax)
