"""Configuration schema for Anantham.

Every parameter named in SIH26169 is a field here, with the PS default and the PS
range attached as metadata. ``validate`` checks a configuration against those ranges
and returns a list of :class:`Issue` objects; the GUI shows them in red and the CLI
refuses to run an out-of-spec configuration unless ``--allow-out-of-spec`` is given.

Units
-----
* ``px``  image pixels of the narrow camera (pixel centres at ``i + 0.5``)
* ``screen px``  pixels of the virtual screen; the screen is an angular grid with the
  same nominal IFOV as the camera (1 screen px = FOV_h / res_w degrees).
* ``deg``, ``deg/s``, ``s``, ``Hz``, ``DN`` (8-bit digital numbers).
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Field metadata helpers
# ---------------------------------------------------------------------------


def ps(
    default: Any,
    lo: float | None = None,
    hi: float | None = None,
    note: str = "",
    choices: tuple[str, ...] | None = None,
    hard_lo: float | None = None,
    hard_hi: float | None = None,
    unit: str = "",
) -> Any:
    """Declare a dataclass field carrying its PS range.

    ``lo``/``hi`` are the problem-statement limits (violations are *PS issues*);
    ``hard_lo``/``hard_hi`` are physical limits (violations are *errors* that make
    the configuration unusable).
    """
    meta = {
        "ps_lo": lo,
        "ps_hi": hi,
        "note": note,
        "choices": choices,
        "hard_lo": hard_lo,
        "hard_hi": hard_hi,
        "unit": unit,
    }
    if isinstance(default, (list, dict)):
        return field(default_factory=lambda d=default: copy.deepcopy(d), metadata=meta)
    return field(default=default, metadata=meta)


MOTIONS = ("stationary", "straight", "circular", "figure8", "random", "spiral",
           "sinusoidal", "waypoints")
SHAPES = ("square", "rectangle", "circle", "gaussian")
ATMOSPHERES = ("clear", "haze", "fog", "rain", "low_light")
TURBULENCE = ("none", "weak", "moderate", "strong", "custom")
PLATFORM = ("none", "linear", "circular", "random", "spiral", "figure8")
STARTS = ("random", "centre", "in_fov", "user")
PERCEPTION_MODES = ("classical", "hybrid", "cnn")
ACQ_MODES = ("spiral", "wide_fov")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass
class CameraConfig:
    """Virtual screen, narrow camera and pan/tilt actuator (PS 'Camera' + 'Pan/tilt')."""

    screen_w_px: int = ps(2000, 2000, None, "PS: screen ≥ 2000×2000 px", hard_lo=64, unit="px")
    screen_h_px: int = ps(2000, 2000, None, "PS: screen ≥ 2000×2000 px", hard_lo=64, unit="px")
    res_w: int = ps(640, 640, 640, "PS: resolution 640×480", hard_lo=32, unit="px")
    res_h: int = ps(480, 480, 480, "PS: resolution 640×480", hard_lo=32, unit="px")
    fov_h_deg: float = ps(4.0, None, None, "PS: FOV user-defined, default 4°×3°",
                          hard_lo=0.05, hard_hi=90.0, unit="deg")
    fov_v_deg: float = ps(3.0, None, None, "PS: FOV user-defined, default 4°×3°",
                          hard_lo=0.05, hard_hi=90.0, unit="deg")
    fps: float = ps(30.0, 30.0, None, "PS: camera update rate ≥ 30 Hz", hard_lo=1.0,
                    hard_hi=1000.0, unit="Hz")
    color: bool = ps(False, note="PS: monochrome focal plane array (colour optional)")
    max_pan_rate_deg_s: float = ps(5.0, 5.0, 10.0, "PS: max pan speed 5–10 °/s",
                                   hard_lo=0.01, unit="deg/s")
    max_tilt_rate_deg_s: float = ps(5.0, 5.0, 10.0, "PS: max tilt speed 5–10 °/s",
                                    hard_lo=0.01, unit="deg/s")
    control_rate_hz: float = ps(30.0, 20.0, None, "PS: control update ≥ 20 Hz",
                                hard_lo=1.0, unit="Hz")
    command_latency_frames: int = ps(0, None, None, "Extra actuation delay (frames)",
                                     hard_lo=0, hard_hi=10, unit="frames")
    initial_pan_deg: float = ps(0.0, note="PS: initial camera position = centre of screen",
                                unit="deg")
    initial_tilt_deg: float = ps(0.0, note="PS: initial camera position = centre of screen",
                                 unit="deg")
    background_dn: float = ps(25.0, None, None, "Mean sky/screen background level",
                              hard_lo=0, hard_hi=200, unit="DN")
    star_density: float = ps(0.5, None, None, "Faint clutter stars per 100×100 screen px",
                             hard_lo=0, hard_hi=10)


@dataclass
class BlinkConfig:
    """Optional blink-code identification of the designated beacon."""

    enabled: bool = ps(False, note="Designated beacon dims periodically (identity code)")
    freq_hz: float = ps(4.0, None, None, "Blink frequency", hard_lo=0.5, hard_hi=14.0, unit="Hz")
    dim_factor: float = ps(0.45, None, None, "Relative intensity in the dim phase",
                           hard_lo=0.0, hard_hi=0.95)
    duty: float = ps(0.5, None, None, "Fraction of the period at full intensity",
                     hard_lo=0.1, hard_hi=0.9)


@dataclass
class DistractorConfig:
    """A non-designated beacon (multiple-target option / identity test)."""

    size_px: float = ps(6.0, 5.0, 20.0, "PS: target size 5–20 px", hard_lo=1.0, unit="px")
    intensity_dn: float = ps(180.0, None, None, "Beacon plateau level", hard_lo=0, unit="DN")
    motion: str = ps("straight", choices=MOTIONS)
    speed_deg_s: float = ps(0.6, None, None, "Beacon speed", hard_lo=0, unit="deg/s")
    blink_freq_hz: float = ps(0.0, None, None, "0 = steady; else its own blink frequency",
                              hard_lo=0, unit="Hz")
    start_x_px: float | None = ps(None, note="Screen px (None = random)")
    start_y_px: float | None = ps(None, note="Screen px (None = random)")


@dataclass
class TargetConfig:
    """Designated beacon (PS 'Target' + 'Motion')."""

    present: bool = ps(True, note="False = target-absent test (no lock must occur)")
    shape: str = ps("square", choices=SHAPES, note="PS: shape user-defined, default square")
    size_px: float = ps(10.0, 5.0, 20.0, "PS: size 5–20 px, default 10×10", hard_lo=1.0,
                        unit="px")
    size_h_px: float = ps(10.0, 5.0, 20.0, "Height for 'rectangle' shape", hard_lo=1.0,
                          unit="px")
    intensity_dn: float = ps(180.0, None, None, "Beacon plateau level above background",
                             hard_lo=0, hard_hi=255, unit="DN")
    psf_sigma_px: float = ps(0.8, None, None, "Optical PSF Gaussian sigma", hard_lo=0.05,
                             hard_hi=10, unit="px")
    start: str = ps("random", choices=STARTS, note="PS: initial location user-defined, "
                    "default random")
    start_x_px: float = ps(1000.0, note="Screen px, used when start = user", unit="px")
    start_y_px: float = ps(1000.0, note="Screen px, used when start = user", unit="px")
    motion: str = ps("circular", choices=MOTIONS, note="PS: straight/circular/figure-8/"
                     "random mandatory; spiral/sinusoidal/waypoints optional")
    speed_deg_s: float = ps(1.0, None, None, "Beacon angular speed on the screen",
                            hard_lo=0, hard_hi=30, unit="deg/s")
    radius_px: float = ps(350.0, None, None, "Radius / amplitude of curved paths",
                          hard_lo=1, unit="px")
    waypoints: list = ps([], note="User waypoint path [[x, y], ...] in screen px")
    margin_px: float | None = ps(None, note="Trajectory margin from screen edge; "
                                 "None = half FOV + 20 px")
    blink: BlinkConfig = field(default_factory=BlinkConfig)
    distractors: list = ps([], note="List of DistractorConfig dicts")
    occlusions: list = ps([], note="[[start_s, duration_s], ...] target hidden")


@dataclass
class TurbulenceConfig:
    """Atmospheric turbulence model (weak / moderate / strong presets or custom)."""

    preset: str = ps("none", choices=TURBULENCE)
    scint_index: float = ps(0.0, None, None, "Scintillation index σ_I² (log-normal)",
                            hard_lo=0, hard_hi=3)
    aoa_sigma_px: float = ps(0.0, None, None, "Angle-of-arrival jitter sigma", hard_lo=0,
                             hard_hi=30, unit="px")
    aoa_tau_s: float = ps(0.1, None, None, "AoA correlation time", hard_lo=0.001, unit="s")
    psf_broadening_px: float = ps(0.0, None, None, "Extra PSF sigma (beam spread)",
                                  hard_lo=0, hard_hi=10, unit="px")


@dataclass
class DisturbanceConfig:
    """Noise, atmosphere, turbulence, jitter and platform motion (PS 'Noise' … 'Platform')."""

    gaussian: bool = ps(True, note="PS: Gaussian noise (selectable)")
    gaussian_sigma: float = ps(2.0, 0.0, 20.0, "PS: max noise std 20 (user-defined)",
                               hard_lo=0, hard_hi=128, unit="DN")
    poisson: bool = ps(True, note="PS: Poisson noise (selectable)")
    poisson_gain: float = ps(0.1, None, None, "DN per photo-electron (bigger = noisier)",
                             hard_lo=1e-4, hard_hi=20)
    salt_pepper: bool = ps(False, note="PS: salt & pepper (~10% of image)")
    sp_fraction: float = ps(0.10, 0.0, 0.10, "PS: ~10% of image", hard_lo=0, hard_hi=0.5)
    atmosphere: str = ps("clear", choices=ATMOSPHERES, note="PS: clear/haze/fog/rain/low light")
    contrast: float | None = ps(None, None, None, "Override: contrast (transmission) 0–1",
                                hard_lo=0.0, hard_hi=1.0)
    brightness: float | None = ps(None, None, None, "Override: brightness factor 0–1",
                                  hard_lo=0.0, hard_hi=1.0)
    turbulence: TurbulenceConfig = field(default_factory=TurbulenceConfig)
    jitter_px: float = ps(0.0, 0.0, 20.0, "PS: camera jitter up to ±20 px/frame",
                          hard_lo=0, hard_hi=100, unit="px/frame")
    jitter_dist: str = ps("uniform", choices=("uniform", "gaussian"),
                          note="uniform in ±J, or Gaussian σ=J/3 clipped at ±J")
    platform: str = ps("none", choices=PLATFORM, note="PS: linear (default) / circular / "
                       "random / spiral / figure-8")
    platform_rate_px: float = ps(0.0, 0.0, 20.0, "PS: platform up to ±20 px/frame",
                                 hard_lo=0, hard_hi=100, unit="px/frame")
    platform_amplitude_px: float = ps(100.0, None, None, "Peak platform LOS excursion",
                                      hard_lo=0, unit="px")


@dataclass
class PerceptionConfig:
    """Detector configuration (classical pipeline + optional CNN verifier)."""

    mode: str = ps("hybrid", choices=PERCEPTION_MODES,
                   note="classical | hybrid (classical + CNN verifier) | cnn (CNN only)")
    tophat_factor: float = ps(2.5, None, None, "Top-hat kernel = factor·s + add",
                              hard_lo=1.0, hard_hi=6.0)
    tophat_add: float = ps(4.0, None, None, "Top-hat kernel additive term", hard_lo=0,
                           unit="px")
    border_px: int = ps(4, None, None, "Zeroed image border", hard_lo=0, hard_hi=64, unit="px")
    k_mad: float = ps(6.0, None, None, "Threshold = median + k·MAD·1.4826", hard_lo=1, hard_hi=50)
    min_noise_dn: float = ps(1.0, None, None, "Floor for the robust noise estimate",
                             hard_lo=0.1, unit="DN")
    size_tolerance: float = ps(0.33, None, None, "Log-size tolerance of the size match",
                               hard_lo=0.05, hard_hi=2.0)
    max_candidates: int = ps(25, None, None, "Candidates kept per frame", hard_lo=1, hard_hi=500)
    cnn_threshold: float = ps(0.5, None, None, "CNN beacon probability to accept",
                              hard_lo=0, hard_hi=1)
    cnn_refine_centroid: bool = ps(False, note="Use CNN heatmap instead of the moment "
                                   "centroid when the classical centroid is edge-clipped")
    model_path: str = ps("", note="ONNX model; empty = bundled anantham/models/verifier.onnx")
    expected_size_px: float | None = ps(None, note="Designated spot size; None = target "
                                        "size (sim) or adaptive estimate (video)")


@dataclass
class TrackerConfig:
    """Identity gate, Kalman filter and state machine."""

    use_kalman: bool = ps(True, note="Ablation switch")
    identity_gate: bool = ps(True, note="Temporal identity gate + signature checks (ablation)")
    confirm_frames: int = ps(3, None, None, "CANDIDATE → LOCKED consistent detections",
                             hard_lo=1, hard_hi=30)
    start_size_match: float = ps(0.7, None, None, "Min size-match to start a track",
                                 hard_lo=0, hard_hi=1)
    assoc_size_match: float = ps(0.5, None, None, "Min size-match to associate",
                                 hard_lo=0, hard_hi=1)
    min_start_score: float = ps(0.35, None, None, "Min signature score to start a track",
                                hard_lo=0, hard_hi=1)
    gate_base_px: float = ps(6.0, None, None, "Gate = base + n_sigma·σ_KF", hard_lo=0.5,
                             unit="px")
    gate_n_sigma: float = ps(3.0, None, None, "Gate sigma multiplier", hard_lo=0.5)
    q_accel: float = ps(1.0, None, None, "Process noise (px/frame²)²", hard_lo=1e-6)
    r_base_px: float = ps(0.35, None, None, "Base measurement sigma", hard_lo=1e-3, unit="px")
    adaptive_r: bool = ps(True, note="R grows with low SNR, edge clipping, measured jitter")
    manoeuvre: bool = ps(True, note="Manoeuvre detection + velocity covariance inflation")
    manoeuvre_nis: float = ps(16.0, None, None, "NIS threshold for manoeuvre", hard_lo=1)
    coast_s: float = ps(0.33, None, None, "COAST duration before RECOVER", hard_lo=0, unit="s")
    recover_s: float = ps(2.0, None, None, "Max RECOVER duration before SEARCH", hard_lo=0,
                          unit="s")
    blink_verify: bool | None = ps(None, note="None = follow target.blink.enabled")
    blink_window_s: float = ps(0.5, None, None, "Blink verification window (≤ 0.5 s)",
                               hard_lo=0.1, hard_hi=2.0, unit="s")
    blink_power_min: float = ps(0.45, None, None, "Min fraction of variance at code freq",
                                hard_lo=0, hard_hi=1)


@dataclass
class ControlConfig:
    """Pan/tilt controller."""

    kp: float = ps(0.55, None, None, "Proportional gain (per frame)", hard_lo=0, hard_hi=2)
    ki: float = ps(0.005, None, None, "Integral gain", hard_lo=0, hard_hi=1)
    kd: float = ps(0.05, None, None, "Derivative gain", hard_lo=0, hard_hi=2)
    feedforward: bool = ps(True, note="Velocity feed-forward (ablation switch)")
    ff_gain: float = ps(1.0, None, None, "Feed-forward gain", hard_lo=0, hard_hi=2)
    latency_frames: float = ps(0.0, None, None, "Latency compensation (aim = pred + v·L)",
                               hard_lo=0, hard_hi=10, unit="frames")
    deadband_px: float = ps(0.25, None, None, "Error deadband", hard_lo=0, unit="px")
    uncertainty_scaling: bool = ps(True, note="Scale gains down as Kalman σ grows")
    sigma0_px: float = ps(12.0, None, None, "σ at which gains halve", hard_lo=0.1, unit="px")
    integral_limit_px: float = ps(100.0, None, None, "Integrator clamp", hard_lo=0, unit="px")


@dataclass
class AcquisitionConfig:
    """Acquisition (search) and recovery."""

    mode: str = ps("spiral", choices=ACQ_MODES, note="spiral = single camera (default); "
                   "wide_fov = OPTIONAL separate wide-FOV acquisition sensor")
    step_fraction: float = ps(0.85, None, None, "Spiral step as a fraction of the FOV",
                              hard_lo=0.1, hard_hi=1.0)
    local_step_fraction: float = ps(0.45, None, None, "Recovery spiral step / FOV",
                                    hard_lo=0.05, hard_hi=1.0)
    local_rings: int = ps(2, None, None, "Recovery spiral rings", hard_lo=0, hard_hi=10)
    local_spiral: bool = ps(True, note="Local recovery spiral (ablation switch)")
    wide_downscale: int = ps(4, None, None, "Wide sensor: whole screen at 1/N resolution",
                             hard_lo=1, hard_hi=16)
    wide_confirm_frames: int = ps(2, None, None, "Wide-sensor frames before hand-off",
                                  hard_lo=1, hard_hi=10)


@dataclass
class RunConfig:
    """Run bookkeeping (seed, duration, outputs)."""

    name: str = ps("run")
    seed: int = ps(0, hard_lo=0)
    duration_s: float = ps(20.0, None, None, "Simulation duration", hard_lo=0.1, unit="s")
    dump_every: int = ps(0, None, None, "Save every N-th frame as PNG (0 = off)", hard_lo=0)
    report_pdf: bool = ps(True, note="Write the PDF performance report")


@dataclass
class Config:
    """Top-level Anantham configuration."""

    camera: CameraConfig = field(default_factory=CameraConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    disturbances: DisturbanceConfig = field(default_factory=DisturbanceConfig)
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    acquisition: AcquisitionConfig = field(default_factory=AcquisitionConfig)
    run: RunConfig = field(default_factory=RunConfig)


# ---------------------------------------------------------------------------
# dict <-> dataclass
# ---------------------------------------------------------------------------


def to_dict(obj: Any) -> Any:
    """Convert a (nested) config dataclass to plain Python types."""
    if dataclasses.is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


class ConfigError(ValueError):
    """Raised for unknown keys, wrong types or out-of-range values."""


def _coerce(value: Any, current: Any, path: str) -> Any:
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{path}: expected bool, got {value!r}")
        return value
    if isinstance(current, int) and not isinstance(current, bool):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{path}: expected int, got {value!r}")
        return value
    if isinstance(current, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path}: expected number, got {value!r}")
        return float(value)
    return value


def update_from_dict(obj: Any, data: dict, path: str = "") -> Any:
    """Recursively update dataclass ``obj`` in place from ``data`` (strict keys)."""
    names = {f.name: f for f in dataclasses.fields(obj)}
    for key, value in (data or {}).items():
        if key not in names:
            raise ConfigError(f"unknown config key '{path}{key}'")
        current = getattr(obj, key)
        if dataclasses.is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"{path}{key}: expected a mapping")
            update_from_dict(current, value, f"{path}{key}.")
        else:
            setattr(obj, key, _coerce(value, current, f"{path}{key}"))
    return obj


def from_dict(data: dict | None) -> Config:
    """Build a :class:`Config` from a (possibly partial) nested dict."""
    return update_from_dict(Config(), data or {})


def merge(base: Config, overrides: dict | None) -> Config:
    """Return a copy of ``base`` with ``overrides`` applied."""
    return update_from_dict(copy.deepcopy(base), overrides or {})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """A validation finding for one field."""

    path: str
    value: Any
    message: str
    severity: str  # "error" (unusable) or "ps" (outside the PS range)

    def __str__(self) -> str:
        return f"[{self.severity}] {self.path} = {self.value!r}: {self.message}"


def _range_text(lo: float | None, hi: float | None) -> str:
    if lo is not None and hi is not None:
        return f"{lo:g}–{hi:g}" if lo != hi else f"= {lo:g}"
    if lo is not None:
        return f"≥ {lo:g}"
    return f"≤ {hi:g}"


def _check_field(obj: Any, f: dataclasses.Field, path: str, out: list[Issue]) -> None:
    v = getattr(obj, f.name)
    m = f.metadata
    if not m:
        return
    if m.get("choices") and v not in m["choices"]:
        out.append(Issue(path, v, f"must be one of {', '.join(m['choices'])}", "error"))
        return
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return
    hlo, hhi = m.get("hard_lo"), m.get("hard_hi")
    if (hlo is not None and v < hlo) or (hhi is not None and v > hhi):
        out.append(Issue(path, v, f"physically invalid, allowed {_range_text(hlo, hhi)}",
                         "error"))
        return
    lo, hi = m.get("ps_lo"), m.get("ps_hi")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        out.append(Issue(path, v, f"outside PS range {_range_text(lo, hi)} ({m['note']})",
                         "ps"))


def _walk(obj: Any, prefix: str, out: list[Issue]) -> None:
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        path = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(v):
            _walk(v, path + ".", out)
        else:
            _check_field(obj, f, path, out)


def validate(cfg: Config) -> list[Issue]:
    """Validate ``cfg`` against the PS ranges and physical limits."""
    out: list[Issue] = []
    _walk(cfg, "", out)
    for i, d in enumerate(cfg.target.distractors):
        try:
            dc = update_from_dict(DistractorConfig(), d, f"target.distractors[{i}].")
        except ConfigError as exc:
            out.append(Issue(f"target.distractors[{i}]", d, str(exc), "error"))
            continue
        _walk(dc, f"target.distractors[{i}].", out)
    if cfg.camera.control_rate_hz > cfg.camera.fps:
        out.append(Issue("camera.control_rate_hz", cfg.camera.control_rate_hz,
                         "cannot exceed the camera rate", "error"))
    if cfg.target.motion == "waypoints" and len(cfg.target.waypoints) < 2:
        out.append(Issue("target.waypoints", cfg.target.waypoints,
                         "waypoint motion needs ≥ 2 points", "error"))
    for i, occ in enumerate(cfg.target.occlusions):
        if not (isinstance(occ, (list, tuple)) and len(occ) == 2 and occ[1] >= 0):
            out.append(Issue(f"target.occlusions[{i}]", occ, "expected [start_s, dur_s]",
                             "error"))
    n_targets = 1 + len(cfg.target.distractors)
    if n_targets > 8:
        out.append(Issue("target.distractors", n_targets, "at most 8 beacons", "error"))
    return out


def field_meta(path: str) -> dict:
    """Return the metadata (PS range, note, unit) of a dotted field path."""
    obj: Any = Config()
    parts = path.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    for f in dataclasses.fields(obj):
        if f.name == parts[-1]:
            return dict(f.metadata)
    raise KeyError(path)


def distractor_configs(cfg: Config) -> list[DistractorConfig]:
    """Parse ``cfg.target.distractors`` into :class:`DistractorConfig` objects."""
    return [update_from_dict(DistractorConfig(), d) for d in cfg.target.distractors]
