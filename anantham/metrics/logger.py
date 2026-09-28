"""Per-frame logging (metrics side of the sensor boundary — may see ground truth).

Two CSVs are written per run:

* ``<name>_frames.csv``  deterministic per-frame record (same config + seed → same bytes)
* ``<name>_timing.csv``  wall-clock timings (processing / render), naturally non-deterministic

plus ``<name>_centroids.csv`` in the evaluator format ``frame,time_s,x_px,y_px,state,confidence``.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

FRAME_COLUMNS = [
    "frame", "t_s", "state", "mode", "meas_valid", "meas_x", "meas_y", "pred_x", "pred_y",
    "confidence", "snr", "n_candidates", "sigma_px", "gate_px", "manoeuvre",
    "pan_deg", "tilt_deg", "pan_rate_dps", "tilt_rate_dps",
    "true_visible", "true_in_fov", "true_x", "true_y", "geo_x", "geo_y", "bore_x", "bore_y",
    "centroid_err_px", "track_err_px", "track_err_ctrl_px",
]
TIMING_COLUMNS = ["frame", "proc_ms", "perc_ms", "track_ms", "ctrl_ms", "render_ms"]
NAN = float("nan")


def _r(v: float | None, nd: int = 4) -> float:
    if v is None:
        return NAN
    v = float(v)
    return v if math.isnan(v) else round(v, nd)


def designated(truth: dict | None) -> dict | None:
    """The designated beacon's truth record (or None)."""
    if not truth:
        return None
    for b in truth.get("beacons", []):
        if b.get("designated"):
            return b
    return None


class FrameLogger:
    """Collects per-frame rows in memory and writes them at the end of the run."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.timing: list[dict] = []
        self.events: list[str] = []

    def log(self, frame, out, truth: dict | None, applied_rate: tuple[float, float]) -> dict:
        """Record one frame; returns the row (with errors computed from truth)."""
        b = designated(truth)
        vis = bool(b and b["visible"])
        in_fov = bool(b and b["in_fov"])
        tx = b["app_x"] if b and vis else NAN
        ty = b["app_y"] if b and vis else NAN
        gx = b["geo_x"] if b and vis else NAN
        gy = b["geo_y"] if b and vis else NAN
        cx = b["ctrl_x"] if b and vis else NAN
        cy = b["ctrl_y"] if b and vis else NAN
        bx, by = truth["bore_img"] if truth and "bore_img" in truth else (NAN, NAN)
        m = out.meas_img
        cerr = math.hypot(m[0] - tx, m[1] - ty) if (m is not None and vis) else NAN
        terr = math.hypot(gx - bx, gy - by) if vis else NAN
        terr_c = math.hypot(cx - bx, cy - by) if vis else NAN
        row = {
            "frame": frame.index, "t_s": _r(frame.t, 5), "state": out.state, "mode": out.mode,
            "meas_valid": int(m is not None),
            "meas_x": _r(m[0] if m else None), "meas_y": _r(m[1] if m else None),
            "pred_x": _r(out.pred_img[0] if out.pred_img else None),
            "pred_y": _r(out.pred_img[1] if out.pred_img else None),
            "confidence": _r(out.confidence), "snr": _r(out.snr, 2),
            "n_candidates": len(out.candidates), "sigma_px": _r(out.sigma),
            "gate_px": _r(out.gate), "manoeuvre": int(out.manoeuvre),
            "pan_deg": _r(frame.pointing_deg[0], 6), "tilt_deg": _r(frame.pointing_deg[1], 6),
            "pan_rate_dps": _r(applied_rate[0], 5), "tilt_rate_dps": _r(applied_rate[1], 5),
            "true_visible": int(vis), "true_in_fov": int(in_fov),
            "true_x": _r(tx), "true_y": _r(ty), "geo_x": _r(gx), "geo_y": _r(gy),
            "bore_x": _r(bx), "bore_y": _r(by),
            "centroid_err_px": _r(cerr), "track_err_px": _r(terr), "track_err_ctrl_px": _r(terr_c),
        }
        self.rows.append(row)
        self.timing.append({"frame": frame.index, "proc_ms": round(out.proc_ms, 4),
                            "perc_ms": round(out.perc_ms, 4), "track_ms": round(out.track_ms, 4),
                            "ctrl_ms": round(out.ctrl_ms, 4), "render_ms": round(frame.render_ms, 4)})
        for e in out.events:
            self.events.append(f"frame {frame.index} t={frame.t:.3f}s {e}")
        return row

    def write(self, out_dir: Path, name: str) -> dict[str, Path]:
        """Write the CSVs; returns their paths."""
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = {"frames": out_dir / f"{name}_frames.csv",
                 "timing": out_dir / f"{name}_timing.csv",
                 "centroids": out_dir / f"{name}_centroids.csv"}
        _write(paths["frames"], FRAME_COLUMNS, self.rows)
        _write(paths["timing"], TIMING_COLUMNS, self.timing)
        cent = [{"frame": r["frame"], "time_s": r["t_s"],
                 "x_px": r["meas_x"] if r["meas_valid"] else "",
                 "y_px": r["meas_y"] if r["meas_valid"] else "",
                 "state": r["state"], "confidence": r["confidence"]} for r in self.rows]
        _write(paths["centroids"], ["frame", "time_s", "x_px", "y_px", "state", "confidence"], cent)
        return paths


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("nan" if isinstance(r[k], float) and math.isnan(r[k]) else r[k])
                        for k in cols})
