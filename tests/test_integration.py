"""Integration: three short scenarios finish and produce reports."""

import json

import pytest

from anantham.bench.scenarios import scenario_config
from anantham.pipeline.session import run_simulation


@pytest.mark.parametrize("name", ["circular", "salt_pepper", "blink"])
def test_short_scenarios_write_reports(tmp_path, name):
    cfg = scenario_config(name, 1, extra={"run": {"duration_s": 3.0},
                                          "target": {"start": "in_fov"},
                                          "perception": {"mode": "classical"}})
    s, paths = run_simulation(cfg, tmp_path, name, pdf=True)
    for k in ("frames", "timing", "centroids", "summary", "config", "log", "report"):
        assert paths[k].exists() and paths[k].stat().st_size > 0, k
    j = json.loads(paths["summary"].read_text())
    assert j["seed"] == 1 and j["name"] == name
    assert any(r["metric"].startswith("Acquisition") for r in j["pass_fail"])
    assert s["acquired"]
    assert paths["report"].read_bytes()[:4] == b"%PDF"
