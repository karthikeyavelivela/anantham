"""Constant-velocity Kalman filter in the gimbal-compensated pointing frame.

State ``[u, v, vu, vv]`` (pointing px, px/frame), dt = 1 frame. Because measurements are
formed as *commanded pointing + image offset*, the camera's own slew is removed exactly
and the filter sees only target (plus platform) motion.

Includes adaptive measurement noise, manoeuvre handling (velocity covariance inflation)
and an IMM stub for a later upgrade.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

F = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], float)
H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)


def q_matrix(q: float) -> np.ndarray:
    """Discrete white-acceleration process noise for dt = 1."""
    b = np.array([[0.25, 0.5], [0.5, 1.0]]) * q
    Q = np.zeros((4, 4))
    Q[np.ix_([0, 2], [0, 2])] = b
    Q[np.ix_([1, 3], [1, 3])] = b
    return Q


class KalmanCV:
    """Constant-velocity Kalman filter (can be disabled for the ablation study).

    When ``enabled`` is False the filter degenerates to "last measurement, zero
    velocity" so the rest of the stack runs unchanged.
    """

    def __init__(self, z: np.ndarray, r: float, q: float, enabled: bool = True):
        self.enabled = enabled
        self.x = np.array([z[0], z[1], 0.0, 0.0], float)
        self.P = np.diag([r * r + 1.0, r * r + 1.0, 25.0, 25.0])
        self.Q = q_matrix(q)
        self.r = r

    # --- core -----------------------------------------------------------------
    def predict(self) -> np.ndarray:
        """Advance one frame; returns the predicted state."""
        if self.enabled:
            self.x = F @ self.x
            self.P = F @ self.P @ F.T + self.Q
        else:
            self.P = self.P + np.diag([4.0, 4.0, 0, 0])
        return self.x

    def innovation(self, z: np.ndarray, r: float) -> tuple[np.ndarray, np.ndarray]:
        """Innovation vector and covariance for measurement ``z`` with sigma ``r``."""
        S = H @ self.P @ H.T + np.eye(2) * r * r
        return z - H @ self.x, S

    def nis(self, z: np.ndarray, r: float) -> float:
        """Normalised innovation squared (Mahalanobis distance²)."""
        nu, S = self.innovation(z, r)
        return float(nu @ np.linalg.solve(S, nu))

    def update(self, z: np.ndarray, r: float) -> None:
        """Measurement update with sigma ``r`` (px)."""
        if not self.enabled:
            v = z - self.x[:2]
            self.x = np.array([z[0], z[1], 0.0, 0.0])
            self.P = np.diag([r * r, r * r, 0.0, 0.0])
            self._last_nu = v
            return
        nu, S = self.innovation(z, r)
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ nu
        I_KH = np.eye(4) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ (np.eye(2) * r * r) @ K.T

    def inflate_velocity(self, nu: np.ndarray) -> None:
        """Manoeuvre response: open up the velocity covariance by the innovation size."""
        if not self.enabled:
            return
        m = float(nu @ nu)
        self.P[2, 2] += m
        self.P[3, 3] += m
        self.P[0, 0] += 0.25 * m
        self.P[1, 1] += 0.25 * m

    # --- accessors ------------------------------------------------------------------
    @property
    def pos(self) -> np.ndarray:
        """Position estimate (pointing px)."""
        return self.x[:2].copy()

    @property
    def vel(self) -> np.ndarray:
        """Velocity estimate (px/frame)."""
        return self.x[2:].copy()

    def sigma_pos(self) -> float:
        """RMS 1-σ position uncertainty (px)."""
        return math.sqrt(max(0.5 * (self.P[0, 0] + self.P[1, 1]), 0.0))

    def gate_sigma(self, r: float) -> float:
        """sqrt of the largest eigenvalue of the innovation covariance (px)."""
        S = H @ self.P @ H.T + np.eye(2) * r * r
        return math.sqrt(float(np.linalg.eigvalsh(S).max()))

    def cov_ellipse(self) -> tuple[float, float, float]:
        """1-σ position ellipse → (semi-major, semi-minor, angle rad)."""
        vals, vecs = np.linalg.eigh(self.P[:2, :2])
        vals = np.clip(vals, 0, None)
        return (math.sqrt(vals[1]), math.sqrt(vals[0]), math.atan2(vecs[1, 1], vecs[0, 1]))


class NoiseEstimator:
    """Measures measurement noise from second differences of recent measurements.

    For a (locally) constant-velocity target, d2 = z_k − 2 z_{k−1} + z_{k−2} has variance
    6σ² for white noise σ. The median-based estimate is robust to occasional manoeuvres.
    This is how "known jitter" enters R without the tracker ever seeing ground truth.
    """

    def __init__(self, n: int = 30):
        self.z: deque = deque(maxlen=3)
        self.d2: deque = deque(maxlen=n)

    def add(self, z: np.ndarray | None) -> None:
        """Add a measurement (None breaks the chain)."""
        if z is None:
            self.z.clear()
            return
        self.z.append(np.asarray(z, float))
        if len(self.z) == 3:
            d = self.z[2] - 2 * self.z[1] + self.z[0]
            self.d2.append(float(d @ d) / 2.0)

    def sigma(self) -> float:
        """Estimated per-axis measurement noise sigma (px); 0 until enough samples."""
        if len(self.d2) < 8:
            return 0.0
        # each sample is (d2x² + d2y²)/2 ~ 6σ²·χ²(2)/2; median of χ²(2)/2 = ln 2
        return math.sqrt(float(np.median(self.d2)) / 6.0 / math.log(2.0))


class IMMStub:
    """Placeholder for an Interacting Multiple Model filter (CV + CA + CT).

    Not used yet; kept so the interface for a future upgrade is fixed:
    ``predict()``, ``update(z, r)``, ``pos``, ``vel``, ``sigma_pos()``.
    """

    def __init__(self, *args, **kwargs):  # pragma: no cover - stub
        raise NotImplementedError("IMM is future work; use KalmanCV")
