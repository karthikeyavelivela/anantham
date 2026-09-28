"""Configuration validation against the PS ranges."""

import pytest

from anantham.config import ConfigError, from_dict, list_presets, load_preset, validate


def test_defaults_valid_and_ps():
    cfg = from_dict({})
    assert validate(cfg) == []
    c = cfg.camera
    assert (c.screen_w_px, c.screen_h_px, c.res_w, c.res_h) == (2000, 2000, 640, 480)
    assert (c.fov_h_deg, c.fov_v_deg, c.fps) == (4.0, 3.0, 30.0)
    assert (c.max_pan_rate_deg_s, c.max_tilt_rate_deg_s) == (5.0, 5.0)
    assert cfg.target.size_px == 10.0 and cfg.target.shape == "square"
    assert cfg.target.start == "random"


@pytest.mark.parametrize("override,path", [
    ({"target": {"size_px": 25}}, "target.size_px"),
    ({"target": {"size_px": 4}}, "target.size_px"),
    ({"camera": {"fps": 25}}, "camera.fps"),
    ({"camera": {"max_pan_rate_deg_s": 12}}, "camera.max_pan_rate_deg_s"),
    ({"camera": {"control_rate_hz": 15}}, "camera.control_rate_hz"),
    ({"camera": {"screen_w_px": 1500}}, "camera.screen_w_px"),
    ({"disturbances": {"gaussian_sigma": 30}}, "disturbances.gaussian_sigma"),
    ({"disturbances": {"jitter_px": 25}}, "disturbances.jitter_px"),
    ({"disturbances": {"platform_rate_px": 25}}, "disturbances.platform_rate_px"),
])
def test_ps_violations_flagged(override, path):
    issues = validate(from_dict(override))
    assert any(i.path == path and i.severity == "ps" for i in issues), issues


def test_errors():
    with pytest.raises(ConfigError):
        from_dict({"camera": {"nonsense": 1}})
    with pytest.raises(ConfigError):
        from_dict({"camera": {"fps": "fast"}})
    issues = validate(from_dict({"target": {"motion": "zigzag"}}))
    assert any(i.severity == "error" for i in issues)
    issues = validate(from_dict({"camera": {"control_rate_hz": 60}}))
    assert any(i.path == "camera.control_rate_hz" and i.severity == "error" for i in issues)


def test_all_presets_load_and_validate():
    names = list_presets()
    assert "default" in names and len(names) >= 35
    for n in names:
        issues = [i for i in validate(load_preset(n)) if i.severity == "error"]
        assert not issues, (n, issues)


def test_presets_match_scenarios():
    from anantham.bench.scenarios import SCENARIOS, scenario_config
    from anantham.config import to_dict

    for n in SCENARIOS:
        a, b = to_dict(load_preset(n)), to_dict(scenario_config(n, 0))
        a["run"], b["run"] = {}, {}
        assert a == b, n
