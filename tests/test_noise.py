"""Statistics of each noise type."""

import numpy as np
import pytest

from anantham.config import from_dict
from anantham.sim.disturbances import apply_noise


def _cfg(**kw):
    d = {"gaussian": False, "poisson": False, "salt_pepper": False}
    d.update(kw)
    return from_dict({"disturbances": d}).disturbances


def test_gaussian_sigma():
    img = np.full((400, 400), 100.0, np.float32)
    out = apply_noise(img, _cfg(gaussian=True, gaussian_sigma=20.0), np.random.default_rng(0))
    assert out.astype(float).std() == pytest.approx(20.0, rel=0.03)
    assert out.astype(float).mean() == pytest.approx(100.0, abs=0.3)


@pytest.mark.parametrize("level", [3.0, 120.0])
def test_poisson_variance(level):
    g = 1.0
    img = np.full((400, 400), level, np.float32)
    out = apply_noise(img, _cfg(poisson=True, poisson_gain=g), np.random.default_rng(0))
    o = out.astype(float)
    assert o.mean() == pytest.approx(level, rel=0.02, abs=0.05)
    assert o.var() == pytest.approx(g * level + 1 / 12, rel=0.05)


def test_salt_pepper_fraction():
    img = np.full((500, 500), 100.0, np.float32)
    out = apply_noise(img, _cfg(salt_pepper=True, sp_fraction=0.10), np.random.default_rng(0))
    salt, pepper = (out == 255).mean(), (out == 0).mean()
    assert salt + pepper == pytest.approx(0.10, abs=0.003)
    assert salt == pytest.approx(pepper, abs=0.004)


def test_quantisation_uint8():
    img = np.full((10, 10), 300.0, np.float32)
    out = apply_noise(img, _cfg(), np.random.default_rng(0))
    assert out.dtype == np.uint8 and out.max() == 255
