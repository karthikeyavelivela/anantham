"""Benchmark scenarios (section 8). Each scenario is a set of overrides on the default config.

The 30 core scenarios are followed by 4 extra checks: target absent (no false lock),
temporary occlusion (re-acquisition), edge exit / re-entry, and a user-waypoint path.
Every scenario is also written as ``config/presets/<name>.yaml``.
"""

from __future__ import annotations

from ..config import Config, from_dict, merge

SMALL_DISTRACTOR = {"size_px": 6.0, "intensity_dn": 180.0, "motion": "straight", "speed_deg_s": 0.6}

SCENARIOS: dict[str, dict] = {
    # --- motion ---------------------------------------------------------------------
    "stationary": {"target": {"motion": "stationary"}},
    "straight_slow": {"target": {"motion": "straight", "speed_deg_s": 0.5}},
    "straight_fast": {"target": {"motion": "straight", "speed_deg_s": 3.0}},
    "circular": {"target": {"motion": "circular", "speed_deg_s": 1.0}},
    "figure8": {"target": {"motion": "figure8", "speed_deg_s": 1.5}},
    "random": {"target": {"motion": "random", "speed_deg_s": 1.0}},
    "spiral": {"target": {"motion": "spiral", "speed_deg_s": 1.0}},
    "sinusoidal": {"target": {"motion": "sinusoidal", "speed_deg_s": 1.0}},
    # --- noise ----------------------------------------------------------------------
    "gauss20": {"disturbances": {"gaussian": True, "gaussian_sigma": 20.0}},
    "poisson": {"disturbances": {"poisson": True, "poisson_gain": 1.0}},
    "salt_pepper": {"disturbances": {"salt_pepper": True, "sp_fraction": 0.10}},
    "mixed_noise": {"disturbances": {"gaussian_sigma": 10.0, "poisson_gain": 0.5,
                                     "salt_pepper": True, "sp_fraction": 0.05}},
    # --- atmosphere -----------------------------------------------------------------
    "haze": {"disturbances": {"atmosphere": "haze"}},
    "fog": {"disturbances": {"atmosphere": "fog"}},
    "rain": {"disturbances": {"atmosphere": "rain"}},
    "low_light": {"disturbances": {"atmosphere": "low_light"}},
    # --- turbulence -----------------------------------------------------------------
    "turb_weak": {"disturbances": {"turbulence": {"preset": "weak"}}},
    "turb_moderate": {"disturbances": {"turbulence": {"preset": "moderate"}}},
    "turb_strong": {"disturbances": {"turbulence": {"preset": "strong"}}},
    # --- jitter / platform ----------------------------------------------------------
    "jitter10": {"disturbances": {"jitter_px": 10.0}},
    "jitter20": {"disturbances": {"jitter_px": 20.0}},
    "platform_linear20": {"disturbances": {"platform": "linear", "platform_rate_px": 20.0,
                                           "platform_amplitude_px": 120.0}},
    "platform_circular10": {"disturbances": {"platform": "circular", "platform_rate_px": 10.0,
                                             "platform_amplitude_px": 80.0}},
    # --- identity / size ------------------------------------------------------------
    "distractor": {"target": {"distractors": [SMALL_DISTRACTOR]}},
    "target5": {"target": {"size_px": 5.0, "size_h_px": 5.0}},
    "target20": {"target": {"size_px": 20.0, "size_h_px": 20.0}},
    "blink": {"target": {"blink": {"enabled": True},
                         "distractors": [dict(SMALL_DISTRACTOR, size_px=10.0)]}},
    # --- combinations ---------------------------------------------------------------
    "fast_noise": {"target": {"motion": "straight", "speed_deg_s": 3.0},
                   "disturbances": {"gaussian_sigma": 15.0, "salt_pepper": True,
                                    "sp_fraction": 0.05}},
    "lowlight_jitter": {"disturbances": {"atmosphere": "low_light", "jitter_px": 10.0}},
    "combined": {"target": {"motion": "figure8", "speed_deg_s": 1.5,
                            "distractors": [SMALL_DISTRACTOR]},
                 "disturbances": {"gaussian_sigma": 10.0, "poisson_gain": 0.5,
                                  "salt_pepper": True, "sp_fraction": 0.05, "atmosphere": "haze",
                                  "turbulence": {"preset": "moderate"}, "jitter_px": 10.0,
                                  "platform": "circular", "platform_rate_px": 10.0,
                                  "platform_amplitude_px": 60.0}},
    # --- extra checks ---------------------------------------------------------------
    "target_absent": {"target": {"present": False}},
    "occlusion": {"target": {"occlusions": [[8.0, 0.5]]}},
    "edge_exit": {"target": {"motion": "waypoints", "speed_deg_s": 1.5, "start": "user",
                             "waypoints": [[1000, 1000], [2300, 1000], [1000, 1000],
                                           [1000, 700]]}},
    "waypoints": {"target": {"motion": "waypoints", "speed_deg_s": 1.2,
                             "waypoints": [[500, 500], [1500, 600], [1400, 1500], [600, 1400]]}},
}

CORE = list(SCENARIOS)[:30]
EXTRA = list(SCENARIOS)[30:]

# Ablation variants (section 8): cumulative switches over the default config.
ABLATION: dict[str, dict] = {
    "classical_only": {"perception": {"mode": "classical"},
                       "tracker": {"use_kalman": False, "identity_gate": False, "manoeuvre": False,
                                   "adaptive_r": False},
                       "control": {"feedforward": False, "uncertainty_scaling": False},
                       "acquisition": {"local_spiral": False}},
    "classical_kalman": {"perception": {"mode": "classical"},
                         "tracker": {"identity_gate": False, "manoeuvre": False,
                                     "adaptive_r": False},
                         "control": {"feedforward": False, "uncertainty_scaling": False},
                         "acquisition": {"local_spiral": False}},
    "cnn_only": {"perception": {"mode": "cnn"},
                 "tracker": {"identity_gate": False, "manoeuvre": False, "adaptive_r": False},
                 "control": {"feedforward": False, "uncertainty_scaling": False},
                 "acquisition": {"local_spiral": False}},
    "hybrid": {"perception": {"mode": "hybrid"},
               "tracker": {"identity_gate": False, "manoeuvre": False, "adaptive_r": False},
               "control": {"feedforward": False, "uncertainty_scaling": False},
               "acquisition": {"local_spiral": False}},
    "hybrid_gate": {"perception": {"mode": "hybrid"},
                    "tracker": {"manoeuvre": False, "adaptive_r": False},
                    "control": {"feedforward": False, "uncertainty_scaling": False},
                    "acquisition": {"local_spiral": False}},
    "hybrid_gate_ff": {"perception": {"mode": "hybrid"},
                       "tracker": {"adaptive_r": False},
                       "control": {"uncertainty_scaling": False},
                       "acquisition": {"local_spiral": False}},
    "full": {"perception": {"mode": "hybrid"}},
}


def scenario_config(name: str, seed: int = 0, base: Config | None = None,
                    extra: dict | None = None) -> Config:
    """Config for scenario ``name`` with ``seed`` (and optional further overrides)."""
    cfg = merge(base or from_dict({}), SCENARIOS[name])
    cfg = merge(cfg, extra or {})
    cfg.run.seed = seed
    cfg.run.name = name
    return cfg
