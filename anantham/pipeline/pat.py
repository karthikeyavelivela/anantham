"""The PAT loop: PERCEIVE → VALIDATE → PREDICT → CONTROL → RECOVER.

``PatSystem.process`` receives ONLY a :class:`~anantham.io.base.Frame` — the rendered
image(s) and the camera's own commanded pointing — and returns a rate command plus
telemetry. It never sees ground truth (enforced by ``tests/test_boundary.py``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config.schema import Config
from ..control.controller import PanTiltController
from ..control.search import (
    SpiralSearch,
    WideAcquisition,
    global_spiral_rings,
    path_time_s,
)
from ..geometry import CameraGeometry
from ..io.base import Frame
from ..perception.classical import Candidate, ClassicalDetector, equivalent_size
from ..tracking.state_machine import State, Tracker


@dataclass
class PatOutput:
    """Per-frame result of the PAT stack (no ground truth inside)."""

    k: int
    t: float
    state: str
    rate_cmd_deg_s: tuple[float, float]
    meas_img: tuple[float, float] | None
    meas_ptg: tuple[float, float] | None
    pred_ptg: tuple[float, float] | None
    pred_img: tuple[float, float] | None
    vel_ptg: tuple[float, float] | None
    sigma: float
    gate: float
    ellipse: tuple[float, float, float] | None
    candidates: list
    snr: float
    confidence: float
    mode: str                                  # track / search / recover / handoff / hold
    search_target: tuple[float, float] | None
    perc_ms: float
    track_ms: float
    ctrl_ms: float
    events: list = field(default_factory=list)
    debug: dict = field(default_factory=dict)
    manoeuvre: bool = False

    @property
    def proc_ms(self) -> float:
        """Processing time: perception + tracking + control (ms)."""
        return self.perc_ms + self.track_ms + self.ctrl_ms


def expected_spot_size(cfg: Config) -> float:
    """Equivalent size (sqrt half-max area) of the designated beacon."""
    if cfg.perception.expected_size_px:
        return float(cfg.perception.expected_size_px)
    t = cfg.target
    return equivalent_size(t.shape, t.size_px, t.size_h_px)


class PatSystem:
    """Perception + tracking + control for one camera."""

    def __init__(self, cfg: Config, geometry: CameraGeometry, fps: float,
                 los_moves: bool = True, screen_px: tuple[float, float] | None = None,
                 spot_size: float | None = None, debug: bool = False):
        self.cfg, self.geom, self.fps = cfg, geometry, fps
        self.los_moves, self.screen = los_moves, screen_px
        self.debug = debug
        self.s = spot_size if spot_size else expected_spot_size(cfg)
        pc = cfg.perception
        self.detector = ClassicalDetector(pc, self.s)
        self.cnn = None
        if pc.mode in ("hybrid", "cnn"):
            from ..perception.cnn import CnnVerifier

            self.cnn = CnnVerifier(pc.model_path or None)
        blink = cfg.tracker.blink_verify
        blink_on = cfg.target.blink.enabled if blink is None else blink
        cam = cfg.camera
        self.umax = (geometry.rate_deg_s_to_px_frame(cam.max_pan_rate_deg_s, fps, "h"),
                     geometry.rate_deg_s_to_px_frame(cam.max_tilt_rate_deg_s, fps, "v"))
        self.tracker = Tracker(cfg.tracker, fps, self.s,
                               cfg.target.blink.freq_hz if blink_on else None, max(self.umax))
        self.ctrl = PanTiltController(cfg.control, self.umax)
        self.ctrl_every = max(int(round(fps / cam.control_rate_hz)), 1)
        self.last_cmd = np.zeros(2)
        acq = cfg.acquisition
        self.global_search: SpiralSearch | None = None
        self.local_search: SpiralSearch | None = None
        self.worst_case_search_s = float("nan")
        if los_moves and screen_px:
            step = (acq.step_fraction * geometry.width, acq.step_fraction * geometry.height)
            rings = global_spiral_rings(screen_px, step, (geometry.width, geometry.height))
            self.bounds = (0.0, 0.0, screen_px[0], screen_px[1])
            self.global_search = SpiralSearch((screen_px[0] / 2, screen_px[1] / 2), step, rings,
                                              self.bounds)
            self.worst_case_search_s = path_time_s(self.global_search.points,
                                                   self.global_search.points[0], self.umax, fps)
        self.wide = None
        if acq.mode == "wide_fov" and los_moves:
            self.wide = WideAcquisition(pc, self.s, acq.wide_downscale,
                                        acq.wide_confirm_frames, fps)
        self.handoff: np.ndarray | None = None
        self.handoff_frames = 0
        self.last_conf = 0.0

    # ------------------------------------------------------------------ PERCEIVE
    def _perceive(self, frame: Frame) -> tuple[list[Candidate], dict, float]:
        img = frame.image
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        pc = self.cfg.perception
        if pc.mode == "cnn":
            dets = self.cnn.detect_full(gray, self.s, pc.cnn_threshold)
            cands = [Candidate(x, y, 0, 0.0, 0.0, 1.0, 10.0, self.s, 1.0, 1.0, p, p, False,
                               (int(x), int(y), 1, 1), cnn_prob=p) for x, y, p in dets]
            res_sigma = 0.0
            dbg = {}
            edge_b = pc.border_px + 0.5 * self.s
            for c in cands:
                c.edge = (c.x < edge_b or c.y < edge_b or c.x > gray.shape[1] - edge_b
                          or c.y > gray.shape[0] - edge_b)
                c.peak = float(gray[min(int(c.y), gray.shape[0] - 1),
                                    min(int(c.x), gray.shape[1] - 1)])
        else:
            res = self.detector.detect(gray, debug=self.debug)
            cands, dbg, res_sigma = res.candidates, res.debug, res.noise_sigma
            # VALIDATE: CNN verifier on plausible candidates
            if pc.mode == "hybrid" and cands:
                check = [c for c in cands if c.size_match >= 0.3]
                ver = self.cnn.verify(gray, [(c.x, c.y) for c in check], self.s)
                for c, (p, hx, hy) in zip(check, ver):
                    c.cnn_prob = p
                    if p < pc.cnn_threshold:
                        c.accepted, c.reason = False, f"cnn-reject p={p:.2f}"
                    elif pc.cnn_refine_centroid and c.edge:
                        c.x, c.y = hx, hy
        for c in cands:
            if self.los_moves:
                c.u, c.v = self.geom.image_to_pointing(c.x, c.y, *frame.bore_px)
            else:
                c.u, c.v = c.x, c.y
        return cands, dbg, res_sigma

    # ------------------------------------------------------------------ main
    def process(self, frame: Frame) -> PatOutput:
        """Run one PAT iteration on ``frame``."""
        t0 = time.perf_counter()
        cands, dbg, _ = self._perceive(frame)
        t1 = time.perf_counter()
        tout = self.tracker.step(cands)                         # PREDICT / associate
        handoff_pt = None
        if self.wide is not None and frame.wide is not None and tout.state == State.SEARCH:
            h = self.wide.step(frame.wide)
            if h is not None:
                handoff_pt = h[0] + h[1] * 3.0
        t2 = time.perf_counter()
        bore = np.asarray(frame.bore_px, float)
        cmd, mode, st = self._control(tout, bore, handoff_pt, frame.index)   # CONTROL/RECOVER
        rate = (self.geom.px_frame_to_deg_s(cmd[0], self.fps, "h"),
                self.geom.px_frame_to_deg_s(cmd[1], self.fps, "v"))
        t3 = time.perf_counter()
        return self._output(frame, tout, cands, rate, mode, st, dbg,
                            (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3)

    def _control(self, tout, bore: np.ndarray, handoff_pt, k: int):
        """Choose tracking / recovery / search command (px/frame)."""
        if k % self.ctrl_every != 0:
            return self.last_cmd, "hold", None
        s = tout.state
        st = None
        if s in (State.LOCKED, State.CANDIDATE, State.COAST) and tout.focus_pos is not None:
            self.local_search = None
            self.handoff = None
            cmd, mode = self.ctrl.track(tout.focus_pos, tout.focus_vel, bore, tout.sigma), "track"
        elif s == State.RECOVER and tout.focus_pos is not None:
            cmd, mode, st = self._recover(tout, bore)
        else:
            cmd, mode, st = self._search(bore, handoff_pt)
        self.last_cmd = cmd
        return cmd, mode, st

    def _recover(self, tout, bore: np.ndarray):
        acq = self.cfg.acquisition
        if not self.los_moves or not acq.local_spiral or acq.local_rings == 0:
            return self.ctrl.track(tout.focus_pos, np.zeros(2), bore, tout.sigma), "recover", None
        if self.local_search is None:
            step = (acq.local_step_fraction * self.geom.width,
                    acq.local_step_fraction * self.geom.height)
            self.local_search = SpiralSearch(tuple(tout.focus_pos), step, acq.local_rings,
                                             self.bounds, loop=True)
        tgt = self.local_search.target(bore)
        return self.ctrl.slew_to(tgt, bore), "recover", (float(tgt[0]), float(tgt[1]))

    def _search(self, bore: np.ndarray, handoff_pt):
        self.local_search = None
        if not self.los_moves:
            c = np.array([self.geom.cx, self.geom.cy])
            return self.ctrl.slew_to(c, bore), "search", (float(c[0]), float(c[1]))
        if handoff_pt is not None:
            self.handoff, self.handoff_frames = handoff_pt, 0
        if self.handoff is not None:
            self.handoff_frames += 1
            limit = int(self.fps * 1.0) + int(max(np.abs(self.handoff - bore) / self.umax))
            if self.handoff_frames > limit:
                self.wide.add_tabu(self.handoff, int(3 * self.fps))
                self.handoff = None
            else:
                t = self.handoff
                return self.ctrl.slew_to(t, bore), "handoff", (float(t[0]), float(t[1]))
        tgt = self.global_search.target(bore)
        return self.ctrl.slew_to(tgt, bore), "search", (float(tgt[0]), float(tgt[1]))

    # ------------------------------------------------------------------ output
    def _output(self, frame: Frame, tout, cands, rate, mode, st, dbg, pm, tm, cm) -> PatOutput:
        m = tout.measurement
        bore = frame.bore_px
        pred_img = None
        if tout.focus_pos is not None:
            if self.los_moves:
                pred_img = self.geom.pointing_to_image(tout.focus_pos[0], tout.focus_pos[1], *bore)
            else:
                pred_img = (float(tout.focus_pos[0]), float(tout.focus_pos[1]))
        conf = 0.0
        if m is not None:
            conf = m.score * (m.cnn_prob if m.cnn_prob is not None else 1.0)
            if tout.state != State.LOCKED:
                conf *= 0.5
        elif tout.state in (State.COAST, State.RECOVER):
            conf = self.last_conf * 0.9
        self.last_conf = conf
        return PatOutput(
            k=frame.index, t=frame.t, state=tout.state.value, rate_cmd_deg_s=rate,
            meas_img=None if m is None else (m.x, m.y),
            meas_ptg=None if m is None else (m.u, m.v),
            pred_ptg=None if tout.focus_pos is None else (float(tout.focus_pos[0]),
                                                           float(tout.focus_pos[1])),
            pred_img=pred_img,
            vel_ptg=None if tout.focus_vel is None else (float(tout.focus_vel[0]),
                                                          float(tout.focus_vel[1])),
            sigma=tout.sigma, gate=tout.gate, ellipse=tout.ellipse, candidates=cands,
            snr=0.0 if m is None else m.snr, confidence=conf, mode=mode,
            search_target=st, perc_ms=pm, track_ms=tm, ctrl_ms=cm, events=tout.events,
            debug=dbg, manoeuvre=tout.manoeuvre)

    def describe(self) -> dict:
        """Static facts for logs: kernel, gates, analytic worst-case search time."""
        return {"spot_size_px": self.s, "tophat_kernel_px": self.detector.kernel_size,
                "max_px_per_frame": list(self.umax),
                "worst_case_spiral_search_s": self.worst_case_search_s,
                "spiral_waypoints": 0 if self.global_search is None else
                len(self.global_search.points),
                "control_every_frames": self.ctrl_every,
                "cnn": None if self.cnn is None else str(self.cnn.path.name),
                "blink_window_frames": self.tracker.blink_n}


