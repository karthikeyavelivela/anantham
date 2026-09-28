"""Kalman filter converges on a constant-velocity target."""

import numpy as np

from anantham.tracking.kalman import KalmanCV, NoiseEstimator


def test_constant_velocity_convergence():
    rng = np.random.default_rng(0)
    v = np.array([3.0, -1.5])
    kf = KalmanCV(np.array([100.0, 100.0]), 0.5, 0.01)
    for k in range(1, 120):
        kf.predict()
        kf.update(np.array([100.0, 100.0]) + v * k + rng.normal(0, 0.5, 2), 0.5)
    assert np.allclose(kf.vel, v, atol=0.3)  # empirical σ_v ≈ 0.09 px/frame over 200 seeds
    assert np.allclose(kf.pos, np.array([100.0, 100.0]) + v * 119, atol=1.0)
    assert kf.sigma_pos() < 0.5


def test_noise_estimator_measures_white_jitter():
    rng = np.random.default_rng(1)
    est = NoiseEstimator(200)
    for k in range(300):
        est.add(np.array([2.0 * k, 5.0]) + rng.normal(0, 4.0, 2))
    assert 3.3 < est.sigma() < 4.8
