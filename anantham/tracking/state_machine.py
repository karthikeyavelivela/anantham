"""Track management and the SEARCH / CANDIDATE / LOCKED / COAST / RECOVER state machine.

SEARCH     no track; the camera follows the acquisition pattern.
CANDIDATE  one or more tentative tracks are accumulating evidence (N consistent
           detections, optional blink verification) — or a recovered track is being
           re-confirmed.
LOCKED     the designated beacon was measured this frame and associated to the track.
COAST      the track was not measured; the Kalman prediction is followed (~0.33 s).
RECOVER    local search around the prediction (the gate keeps growing), then SEARCH.

Only candidates (image-derived) enter here — never ground truth.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from ..config.schema import TrackerConfig
from .gate import blink_statistic, blink_window, gated_nearest
from .kalman import KalmanCV, NoiseEstimator, q_matrix


class State(StrEnum):
    """Tracker states (string-valued for logging)."""

    SEARCH = "SEARCH"
    CANDIDATE = "CANDIDATE"
    LOCKED = "LOCKED"
    COAST = "COAST"
    RECOVER = "RECOVER"


@dataclass
class Track:
    """A tentative or confirmed track."""

    tid: int
    kf: KalmanCV
    hits: int = 1
    consec: int = 1
    misses: int = 0
    age: int = 1
    peaks: deque = field(default_factory=lambda: deque(maxlen=64))
    blink_ok: bool | None = None
    rejected: bool = False
    score_sum: float = 0.0
    noise: NoiseEstimator = field(default_factory=NoiseEstimator)
    last_r: float = 1.0
    big_nu: np.ndarray | None = None          # last large innovation (manoeuvre persistence)
    nis_hist: deque = field(default_factory=lambda: deque(maxlen=10))


@dataclass
class TrackOutput:
    """What the tracker tells the controller and the logger."""

    state: State
    focus_pos: np.ndarray | None = None     # where to point (pointing px)
    focus_vel: np.ndarray | None = None
    sigma: float = 0.0
    gate: float = 0.0
    measurement: object | None = None       # associated Candidate (or None)
    manoeuvre: bool = False
    ellipse: tuple[float, float, float] | None = None
    n_tentative: int = 0
    events: list = field(default_factory=list)
    noise_sigma: float = 0.0
    frames_in_state: int = 0


class Tracker:
    """Identity-gated single-target tracker with tentative-track confirmation."""

    def __init__(self, cfg: TrackerConfig, fps: float, spot_size: float,
                 blink_freq: float | None, max_step_px: float = 30.0):
        self.cfg, self.fps, self.s = cfg, fps, spot_size
        self.max_step = max_step_px
        ig = cfg.identity_gate
        self.confirm_n = cfg.confirm_frames if ig else 1
        self.start_sm = cfg.start_size_match if ig else 0.0
        self.assoc_sm = cfg.assoc_size_match if ig else 0.0
        self.min_score = cfg.min_start_score if ig else 0.0
        self.blink_freq = blink_freq if (ig and blink_freq) else None
        self.blink_n = blink_window(fps, blink_freq, cfg.blink_window_s) if self.blink_freq else 0
        self.state = State.SEARCH
        self.primary: Track | None = None
        self.tentative: list[Track] = []
        self.next_id = 1
        self.frames_in_state = 0
        self.reconfirm = 0
        self.gate_base = max(cfg.gate_base_px, 0.5 * spot_size)

    # --- helpers ---------------------------------------------------------------------
    def _set_state(self, s: State, out: TrackOutput, why: str) -> None:
        if s != self.state:
            out.events.append(f"{self.state.value}->{s.value}: {why}")
            self.state = s
            self.frames_in_state = 0

    def _r(self, c, trk: Track) -> float:
        """Adaptive measurement sigma (px) for candidate ``c``."""
        r = self.cfg.r_base_px
        if not self.cfg.adaptive_r:
            return max(r, 0.5)
        r2 = r * r * (1.0 + (8.0 / max(c.snr, 1.0)) ** 2)
        if c.edge:
            r2 += 0.25 * self.s ** 2
        est = trk.noise.sigma()
        r2 = max(r2, est * est)
        return math.sqrt(r2)

    def _gate(self, trk: Track, tentative: bool = False) -> float:
        r = max(trk.last_r, trk.noise.sigma()) if self.cfg.adaptive_r else trk.last_r
        g = self.gate_base + self.cfg.gate_n_sigma * trk.kf.gate_sigma(r)
        if not self.cfg.use_kalman:
            g = max(g, 3 * self.gate_base)
        if tentative and self.cfg.identity_gate:
            # kinematic bound for the confirmation stage: the apparent step of a trackable
            # target (plus LOS disturbance) is bounded by ~1.5× the slew limit per frame
            g = max(g, self.gate_base + 1.5 * self.max_step)
        return g

    def _adapt_q(self, trk: Track, nis: float) -> None:
        """Scale Q by the recent mean NIS (≈2 when consistent) — handles smooth manoeuvres."""
        if not (self.cfg.adaptive_r and self.cfg.use_kalman):
            return
        trk.nis_hist.append(min(nis, 50.0))
        if len(trk.nis_hist) >= 5:
            scale = min(max(float(np.mean(trk.nis_hist)) / 2.0, 1.0), 25.0)
            trk.kf.Q = q_matrix(self.cfg.q_accel * scale)

    def _new_track(self, c) -> Track:
        trk = Track(self.next_id, KalmanCV(np.array([c.u, c.v]), self.cfg.r_base_px,
                                           self.cfg.q_accel, self.cfg.use_kalman))
        self.next_id += 1
        trk.peaks.append(c.peak)
        trk.score_sum = c.score
        trk.noise.add(np.array([c.u, c.v]))
        return trk

    # --- main entry ------------------------------------------------------------------
    def step(self, cands: list) -> TrackOutput:
        """Process one frame's candidates (with pointing-frame ``u, v`` filled)."""
        out = TrackOutput(self.state)
        self.frames_in_state += 1
        if self.primary is not None:
            self._step_primary(cands, out)
        if self.primary is None:
            self._step_tentative(cands, out)
        out.state = self.state
        out.frames_in_state = self.frames_in_state
        return out

    def _step_primary(self, cands: list, out: TrackOutput) -> None:
        p = self.primary
        kf = p.kf
        if self.state == State.COAST:
            kf.x[2:] *= 0.85  # partial extrapolation: robust to reversals during a dropout
        elif self.state == State.RECOVER:
            kf.x[2:] *= 0.95  # damp velocity while searching locally
        if self.state in (State.COAST, State.RECOVER):
            sp = float(np.hypot(*kf.x[2:]))
            if sp > self.max_step:  # never extrapolate faster than the gimbal can follow
                kf.x[2:] *= self.max_step / sp
        kf.predict()
        p.age += 1
        gate = self._gate(p)
        pred = kf.pos
        idx, _ = gated_nearest(pred, cands, gate, self.assoc_sm)
        outside = False
        if idx < 0 and self.cfg.manoeuvre and self.cfg.identity_gate:
            # a velocity reversal produces an innovation of up to 2|v|
            wide = gate + self.gate_base + 2.0 * float(np.hypot(*kf.vel))
            j, _ = gated_nearest(pred, cands, wide, self.cfg.start_size_match)
            if j >= 0 and cands[j].score >= 0.5 and not cands[j].edge:
                idx, outside = j, True
        if idx >= 0:
            self._update_primary(p, cands[idx], outside, out)
        else:
            self._miss_primary(p, out)
        out.focus_pos, out.focus_vel = kf.pos, kf.vel
        out.sigma, out.gate = kf.sigma_pos(), self._gate(p)
        out.ellipse = kf.cov_ellipse()
        out.noise_sigma = p.noise.sigma()

    def _update_primary(self, p: Track, c, outside: bool, out: TrackOutput) -> None:
        z = np.array([c.u, c.v])
        r = self._r(c, p)
        p.last_r = r
        nu, S = p.kf.innovation(z, r)
        nis = float(nu @ np.linalg.solve(S, nu))
        if self.cfg.manoeuvre and (outside or nis > self.cfg.manoeuvre_nis):
            # a real manoeuvre persists (two large innovations in a consistent direction);
            # a single jitter spike does not — then only the position covariance opens up
            sig_n = max(p.noise.sigma(), self.cfg.r_base_px, 0.5)
            clear = float(np.hypot(*nu)) > 8.0 * sig_n  # far beyond any measured noise
            if clear or (p.big_nu is not None and float(nu @ p.big_nu) > 0):
                p.kf.inflate_velocity(nu)
                out.manoeuvre = True
            elif outside:
                p.kf.P[0, 0] += float(nu @ nu)
                p.kf.P[1, 1] += float(nu @ nu)
            p.big_nu = nu
        else:
            p.big_nu = None
        self._adapt_q(p, nis)
        p.kf.update(z, r)
        p.noise.add(z)
        p.misses = 0
        p.hits += 1
        p.peaks.append(c.peak)
        c.reason = "associated"
        out.measurement = c
        if self.state in (State.LOCKED, State.COAST):
            self._set_state(State.LOCKED, out, "track measured")
        else:  # RECOVER or re-confirming CANDIDATE
            self.reconfirm += 1
            if self.reconfirm >= self.confirm_n:
                self._set_state(State.LOCKED, out, f"re-confirmed ({self.reconfirm} frames)")
            else:
                self._set_state(State.CANDIDATE, out, "re-acquiring")

    def _miss_primary(self, p: Track, out: TrackOutput) -> None:
        p.misses += 1
        p.noise.add(None)
        self.reconfirm = 0
        coast_n = int(round(self.cfg.coast_s * self.fps))
        rec_n = int(round(self.cfg.recover_s * self.fps))
        if self.state in (State.LOCKED, State.CANDIDATE):
            self._set_state(State.COAST if coast_n > 0 else State.RECOVER, out, "no measurement")
        elif self.state == State.COAST and p.misses > coast_n:
            self._set_state(State.RECOVER, out, "coast expired")
        elif self.state == State.RECOVER and self.frames_in_state > rec_n:
            self._set_state(State.SEARCH, out, "recovery failed")
            self.primary = None

    def _step_tentative(self, cands: list, out: TrackOutput) -> None:
        used: set[int] = set()
        for t in sorted(self.tentative, key=lambda t: -t.hits):
            t.kf.predict()
            t.age += 1
            i, _ = gated_nearest(t.kf.pos, cands, self._gate(t, tentative=True), self.assoc_sm,
                                 used)
            if i >= 0:
                c = cands[i]
                used.add(i)
                z = np.array([c.u, c.v])
                r = self._r(c, t)
                t.last_r = r
                t.kf.update(z, r)
                t.noise.add(z)
                t.hits += 1
                t.consec += 1
                t.misses = 0
                t.peaks.append(c.peak)
                t.score_sum += c.score
                c.reason = "rejected-track" if t.rejected else f"tentative#{t.tid}"
                t._last = c  # type: ignore[attr-defined]
            else:
                t.misses += 1
                t.consec = 0
                t.peaks.append(0.0)
                t.noise.add(None)
                t._last = None  # type: ignore[attr-defined]
        keep_misses = max(3, self.blink_n // 3)
        self.tentative = [t for t in self.tentative
                          if t.misses <= (15 if t.rejected else keep_misses)]
        for i, c in enumerate(cands):
            if i in used or not c.accepted:
                continue
            if (c.edge and self.cfg.identity_gate) or c.size_match < self.start_sm \
                    or c.score < self.min_score:
                if not c.reason:
                    c.reason = ("edge" if c.edge and self.cfg.identity_gate else
                                "size-mismatch" if c.size_match < self.start_sm else "low-score")
                continue
            if len(self.tentative) < 6:
                t = self._new_track(c)
                t._last = c  # type: ignore[attr-defined]
                self.tentative.append(t)
                c.reason = f"new-track#{t.tid}"
        self._confirm(out)

    def _confirm(self, out: TrackOutput) -> None:
        ready = []
        for t in self.tentative:
            if t.rejected or t.consec < self.confirm_n or getattr(t, "_last", None) is None:
                continue
            if self.blink_freq:
                if len(t.peaks) < self.blink_n:
                    continue
                frac, depth = blink_statistic(np.array(t.peaks)[-self.blink_n:], self.fps,
                                              self.blink_freq)
                if frac >= self.cfg.blink_power_min and depth >= 0.08:
                    t.blink_ok = True
                elif t.age >= 2 * self.blink_n:
                    t.rejected = True
                    out.events.append(f"track#{t.tid} rejected: blink code not found "
                                      f"(frac={frac:.2f}, depth={depth:.2f})")
                    continue
                else:
                    continue
            ready.append(t)
        live = [t for t in self.tentative if not t.rejected]
        if ready:
            best = max(ready, key=lambda t: t.score_sum / t.hits)
            self.primary = best
            self.reconfirm = self.confirm_n
            self.tentative = []
            self._set_state(State.LOCKED, out, f"track#{best.tid} confirmed")
            out.measurement = best._last  # type: ignore[attr-defined]
            best.misses = 0
            k = best.kf
            out.focus_pos, out.focus_vel, out.sigma = k.pos, k.vel, k.sigma_pos()
            out.gate, out.ellipse = self._gate(best), k.cov_ellipse()
            return
        if live:
            self._set_state(State.CANDIDATE, out, "tentative track")
            best = max(live, key=lambda t: (t.consec, t.score_sum / t.hits))
            out.focus_pos, out.focus_vel = best.kf.pos, best.kf.vel
            out.sigma, out.gate = best.kf.sigma_pos(), self._gate(best)
            out.ellipse = best.kf.cov_ellipse()
        else:
            self._set_state(State.SEARCH, out, "no tentative tracks")
        out.n_tentative = len(live)
