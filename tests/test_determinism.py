"""R4: same config + seed → identical frames and identical per-frame CSV."""

import hashlib

import numpy as np

from anantham.config import from_dict
from anantham.io.sim_source import SimSource
from anantham.pipeline.session import Session


def _run(seed, tmp_path, tag):
    cfg = from_dict({"perception": {"mode": "classical"}, "run": {"duration_s": 2.0, "seed": seed},
                     "disturbances": {"salt_pepper": True, "jitter_px": 5.0,
                                      "turbulence": {"preset": "moderate"}}})
    src = SimSource(cfg)
    s = Session(cfg, src)
    h = hashlib.sha256()
    while (r := s.step()) is not None:
        h.update(np.ascontiguousarray(r.frame.image).tobytes())
    paths = s.logger.write(tmp_path / tag, "d")
    return h.hexdigest(), hashlib.sha256(paths["frames"].read_bytes()).hexdigest()


def test_same_seed_same_output(tmp_path):
    a = _run(7, tmp_path, "a")
    b = _run(7, tmp_path, "b")
    c = _run(8, tmp_path, "c")
    assert a == b
    assert a[0] != c[0]
