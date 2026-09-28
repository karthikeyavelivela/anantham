"""PS performance metrics and PASS/FAIL (definitions in docs/METRICS.md).

All metrics are computed from the per-frame rows written by :class:`FrameLogger`.
Nothing here is estimated or assumed: a metric that cannot be computed is NaN and is
reported as "not measured".
"""

from __future__ import annotations

import math

import numpy as np

PS = {
    "acquisition_s": 2.0,
    "tracking_err_px": 10.0,
    "centroid_err_px": 10.0,
    "target_loss": 0.05,
    "reacq_s": 1.0,
    "processing_fps": 20.0,
    "camera_hz": 30.0,
    "control_hz": 20.0,
}
NAN = float("nan")


def _stats(a: np.ndarray, urad_per_px: float | None = None) -> dict:
    a = a[~np.isnan(a)]
    if a.size == 0:
        return {"n": 0, "mean": NAN, "rmse": NAN, "p95": NAN, "max": NAN}
    d = {"n": int(a.size), "mean": float(a.mean()), "rmse": float(math.sqrt((a * a).mean())),
         "p95": float(np.percentile(a, 95)), "max": float(a.max())}
    if urad_per_px:
        d["rmse_urad"] = d["rmse"] * urad_per_px
    return d


def _col(rows: list[dict], key: str) -> np.ndarray:
    return np.array([float(r[key]) for r in rows], float)


def reacquisition_events(states: list[str], t: np.ndarray, visible: np.ndarray) -> dict:
    """LOCKED → not-LOCKED → LOCKED intervals after the first lock."""
    events, t_loss, t_vis, unrecovered = [], None, None, False
    locked_once = False
    for i, s in enumerate(states):
        lk = s == "LOCKED"
        if lk and not locked_once:
            locked_once = True
            continue
        if not locked_once:
            continue
        if t_loss is None and not lk:
            t_loss, t_vis = t[i], (t[i] if visible[i] else None)
        elif t_loss is not None and not lk:
            if t_vis is None and visible[i]:
                t_vis = t[i]
        elif t_loss is not None and lk:
            events.append({"lost_at_s": float(t_loss), "relocked_at_s": float(t[i]),
                           "duration_s": float(t[i] - t_loss),
                           "after_visible_s": float(t[i] - t_vis) if t_vis is not None else NAN})
            t_loss, t_vis = None, None
    if t_loss is not None:
        unrecovered = True
    d = np.array([e["duration_s"] for e in events]) if events else np.zeros(0)
    av = np.array([e["after_visible_s"] for e in events]) if events else np.zeros(0)
    av = av[~np.isnan(av)]
    return {"count": len(events), "mean_s": float(d.mean()) if d.size else NAN,
            "max_s": float(d.max()) if d.size else NAN,
            "max_after_visible_s": float(av.max()) if av.size else NAN,
            "unrecovered_at_end": unrecovered,
            "unrecovered_since_s": float(t_loss) if unrecovered else NAN, "events": events}


def summarize(rows: list[dict], timing: list[dict], fps: float, control_hz: float,
              urad_per_px: float, has_truth: bool = True, target_present: bool = True) -> dict:
    """Compute every PS metric from per-frame rows."""
    n = len(rows)
    if n == 0:
        return {"n_frames": 0}
    t = _col(rows, "t_s")
    states = [r["state"] for r in rows]
    locked = np.array([s == "LOCKED" for s in states])
    meas = _col(rows, "meas_valid") > 0
    vis = _col(rows, "true_visible") > 0
    in_fov = _col(rows, "true_in_fov") > 0
    cerr, terr, terrc = _col(rows, "centroid_err_px"), _col(rows, "track_err_px"), \
        _col(rows, "track_err_ctrl_px")
    first = int(np.argmax(locked)) if locked.any() else None
    out: dict = {"n_frames": n, "duration_s": n / fps, "camera_hz": fps, "control_hz": control_hz,
                 "has_truth": has_truth, "target_present": target_present}
    out["acquisition_time_s"] = float(t[first]) if first is not None else NAN
    out["acquired"] = first is not None
    out["centroiding_error_px"] = _stats(np.where(meas & vis, cerr, NAN), urad_per_px)
    # tracking error: all locked frames, and steady state (≥ 1 s after the latest (re)lock)
    relock_t = np.full(n, np.inf)
    last = -np.inf
    for i in range(n):
        if locked[i] and (i == 0 or not locked[i - 1]):
            last = t[i]
        relock_t[i] = last
    steady = locked & (t - relock_t >= 1.0)
    out["tracking_error_px"] = _stats(np.where(locked & vis, terr, NAN), urad_per_px)
    out["tracking_error_steady_px"] = _stats(np.where(steady & vis, terr, NAN), urad_per_px)
    out["tracking_error_ctrl_px"] = _stats(np.where(locked & vis, terrc, NAN), urad_per_px)
    out["tracking_error_steady_ctrl_px"] = _stats(np.where(steady & vis, terrc, NAN), urad_per_px)
    out["reacquisition"] = reacquisition_events(states, t, vis)
    if first is not None:
        post = slice(first, n)
        good = locked[post] & meas[post]
        if has_truth:
            good = good & (np.nan_to_num(cerr[post], nan=np.inf) <= PS["centroid_err_px"])
        npost = n - first
        out["lock_retention"] = float(good.sum()) / npost
        out["target_loss"] = 1.0 - out["lock_retention"]
        vpost = in_fov[post] if has_truth else np.ones(npost, bool)
        out["lock_retention_visible"] = (float((good & vpost).sum()) / max(vpost.sum(), 1)
                                         if has_truth else NAN)
        out["detection_coverage"] = float((meas[post] & vpost).sum()) / max(vpost.sum(), 1)
        out["post_acquisition_frames"] = npost
    else:
        for k in ("lock_retention", "target_loss", "lock_retention_visible", "detection_coverage"):
            out[k] = NAN
        out["post_acquisition_frames"] = 0
    wrong = locked & meas & (np.nan_to_num(cerr, nan=0.0) > PS["centroid_err_px"])
    out["wrong_target_locked_frames"] = int(wrong.sum()) if has_truth else None
    out["false_lock_frames"] = int((locked & ~in_fov).sum()) if has_truth else None
    out["locked_frames"] = int(locked.sum())
    out["state_fractions"] = {s: float(np.mean([x == s for x in states]))
                              for s in ("SEARCH", "CANDIDATE", "LOCKED", "COAST", "RECOVER")}
    proc = np.array([r["proc_ms"] for r in timing], float)
    rend = np.array([r["render_ms"] for r in timing], float)
    out["processing_ms"] = {"mean": float(proc.mean()), "p95": float(np.percentile(proc, 95)),
                            "max": float(proc.max())}
    out["processing_fps"] = 1000.0 / max(float(proc.mean()), 1e-9)
    out["render_ms_mean"] = float(rend.mean())
    out["pass_fail"] = pass_fail(out)
    return out


def _pf(name: str, value: float, thr: float, op: str, unit: str, note: str = "") -> dict:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        ok = None
    else:
        ok = bool(value <= thr) if op == "<=" else bool(value < thr) if op == "<" else \
            bool(value >= thr)
    return {"metric": name, "value": value, "threshold": f"{op} {thr:g} {unit}".strip(),
            "pass": ok, "note": note}


def pass_fail(s: dict) -> list[dict]:
    """PASS/FAIL rows against every PS threshold (pass=None → not measured / n/a)."""
    rows = []
    if not s["target_present"]:
        fl = s["locked_frames"]
        rows.append({"metric": "No false lock (target absent)", "value": fl,
                     "threshold": "= 0 LOCKED frames", "pass": fl == 0, "note": ""})
    else:
        acq = s["acquisition_time_s"]
        rows.append(_pf("Acquisition time", acq if s["acquired"] else math.inf,
                        PS["acquisition_s"], "<=", "s",
                        "" if s["acquired"] else "never acquired"))
        rows.append(_pf("Centroiding error (RMSE)", s["centroiding_error_px"]["rmse"],
                        PS["centroid_err_px"], "<=", "px"))
        rows.append(_pf("Tracking error (RMSE, all locked frames)",
                        s["tracking_error_px"]["rmse"], PS["tracking_err_px"], "<=", "px"))
        rows.append(_pf("Tracking error (RMSE, steady state)",
                        s["tracking_error_steady_px"]["rmse"], PS["tracking_err_px"], "<=", "px"))
        rows.append(_pf("Target loss", s["target_loss"], PS["target_loss"], "<", ""))
        ra = s["reacquisition"]
        if ra["unrecovered_at_end"]:
            rows.append({"metric": "Re-acquisition time (max)", "value": math.inf,
                         "threshold": "<= 1 s", "pass": False,
                         "note": f"unrecovered at end (lost at {ra['unrecovered_since_s']:.2f} s)"})
        elif ra["count"] == 0:
            rows.append({"metric": "Re-acquisition time (max)", "value": NAN, "threshold": "<= 1 s",
                         "pass": None, "note": "no loss events"})
        else:
            rows.append(_pf("Re-acquisition time (max)", ra["max_s"], PS["reacq_s"], "<=", "s",
                            f"{ra['count']} events"))
    rows.append(_pf("Processing speed", s["processing_fps"], PS["processing_fps"], ">=", "FPS"))
    rows.append(_pf("Camera update rate", s["camera_hz"], PS["camera_hz"], ">=", "Hz"))
    rows.append(_pf("Control update rate", s["control_hz"], PS["control_hz"], ">=", "Hz"))
    return rows


def overall_pass(s: dict) -> bool:
    """True when every measured PS row passes."""
    return all(r["pass"] is not False for r in s.get("pass_fail", []))
