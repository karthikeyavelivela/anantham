"""Temporal identity gate: a single-frame clutter spike never produces a lock."""

import numpy as np

from anantham.config import from_dict
from anantham.perception.classical import Candidate
from anantham.tracking.gate import blink_statistic
from anantham.tracking.state_machine import State, Tracker


def _cand(u, v, sm=1.0, score=0.9, edge=False, peak=150.0):
    c = Candidate(u, v, 100, peak, 1e4, 1.0, 50.0, 10.0, sm, 1.0, 1.0, score, edge, (0, 0, 1, 1))
    c.u, c.v = u, v
    return c


def _tracker(**kw):
    cfg = from_dict({"tracker": kw}).tracker
    return Tracker(cfg, 30.0, 10.0, None)


def test_single_frame_spike_rejected():
    t = _tracker()
    states = [t.step([_cand(500, 500)]).state]
    for _ in range(10):
        states.append(t.step([]).state)
    assert State.LOCKED not in states


def test_three_consistent_detections_lock():
    t = _tracker()
    out = [t.step([_cand(500 + 2 * k, 500)]).state for k in range(3)]
    assert out[:2] == [State.CANDIDATE, State.CANDIDATE] and out[2] == State.LOCKED


def test_edge_and_size_mismatch_cannot_start():
    t = _tracker()
    for _ in range(5):
        assert t.step([_cand(500, 500, edge=True), _cand(700, 500, sm=0.4)]).state == State.SEARCH


def test_coast_then_recover_then_search():
    t = _tracker()
    for k in range(5):
        t.step([_cand(500 + k, 500)])
    seq = [t.step([]).state for _ in range(90)]
    assert seq[0] == State.COAST and State.RECOVER in seq and seq[-1] == State.SEARCH


def test_blink_statistic():
    fps, f = 30.0, 4.0
    n = np.arange(15)
    on = ((n / fps * f) % 1.0) < 0.5
    blink = np.where(on, 150.0, 70.0)
    frac, depth = blink_statistic(blink, fps, f)
    assert frac > 0.6 and depth > 0.2
    steady = 150 + np.random.default_rng(0).normal(0, 8, 15)
    assert blink_statistic(steady, fps, f)[0] < 0.45


def test_blink_rejects_steady_distractor():
    cfg = from_dict({}).tracker
    t = Tracker(cfg, 30.0, 10.0, 4.0)
    rng = np.random.default_rng(0)
    states = []
    for k in range(60):
        on = ((k / 30.0 * 4.0) % 1.0) < 0.5
        c1 = _cand(300, 300, peak=150 + rng.normal(0, 5))           # steady distractor
        c2 = _cand(600, 400, peak=(150 if on else 68) + rng.normal(0, 5))  # blinking target
        o = t.step([c1, c2])
        states.append(o.state)
        if o.state == State.LOCKED:
            assert abs(o.focus_pos[0] - 600) < 5
            break
    assert State.LOCKED in states
    assert len(states) <= 25  # verified within ~0.5 s window
