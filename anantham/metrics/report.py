"""Automatic performance reports: text, Markdown, JSON (in session) and PDF (matplotlib).

Every number in a report is read from the run's summary / per-frame rows; nothing is
typed in by hand.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

STATE_COLORS = {"SEARCH": "#94A3B8", "CANDIDATE": "#0EA5E9", "LOCKED": "#16A34A",
                "COAST": "#F59E0B", "RECOVER": "#EA580C"}
NAVY = "#1B2A4A"


def fmt(v, nd: int = 2, unit: str = "") -> str:
    """Format a metric; NaN/None → 'not measured'."""
    if v is None:
        return "not measured"
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and math.isnan(v):
        return "not measured"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return f"{v:.{nd}f}{(' ' + unit) if unit else ''}"


def verdict(p) -> str:
    """PASS / FAIL / n/a."""
    return "n/a" if p is None else ("PASS" if p else "FAIL")


def key_metrics(s: dict) -> list[tuple[str, str]]:
    """(label, value) rows of the headline metrics."""
    ce, te, ts = s["centroiding_error_px"], s["tracking_error_px"], s["tracking_error_steady_px"]
    ra = s["reacquisition"]
    pct = lambda v: "not measured" if v is None or (isinstance(v, float) and math.isnan(v)) \
        else f"{100 * v:.2f} %"  # noqa: E731
    return [
        ("Acquisition time", fmt(s["acquisition_time_s"], 3, "s")),
        ("Centroiding error mean / RMSE / P95 / max",
         f"{fmt(ce['mean'], 3)} / {fmt(ce['rmse'], 3)} / {fmt(ce['p95'], 3)} / {fmt(ce['max'], 3)} px"),
        ("Centroiding error RMSE", fmt(ce.get("rmse_urad", float("nan")), 1, "µrad")),
        ("Tracking error (all locked) mean / RMSE / P95 / max",
         f"{fmt(te['mean'])} / {fmt(te['rmse'])} / {fmt(te['p95'])} / {fmt(te['max'])} px"),
        ("Tracking error (steady state ≥1 s after lock) RMSE / P95",
         f"{fmt(ts['rmse'])} / {fmt(ts['p95'])} px"),
        ("Tracking error excl. camera jitter (steady) RMSE",
         fmt(s["tracking_error_steady_ctrl_px"]["rmse"], 2, "px")),
        ("Lock retention rate", pct(s["lock_retention"])),
        ("Target loss", pct(s["target_loss"])),
        ("Detection coverage (post-acq., target in FOV)", pct(s["detection_coverage"])),
        ("Re-acquisitions: count / mean / max",
         f"{ra['count']} / {fmt(ra['mean_s'], 3)} / {fmt(ra['max_s'], 3)} s"
         + (" (UNRECOVERED at end)" if ra["unrecovered_at_end"] else "")),
        ("Wrong-target locked frames", fmt(s.get("wrong_target_locked_frames"), 0)),
        ("Processing time mean / P95 / max",
         f"{fmt(s['processing_ms']['mean'])} / {fmt(s['processing_ms']['p95'])} / "
         f"{fmt(s['processing_ms']['max'])} ms"),
        ("Processing speed", fmt(s["processing_fps"], 1, "FPS")),
        ("Simulation duration / camera rate",
         f"{fmt(s['duration_s'], 2)} s / {fmt(s['camera_hz'], 1)} Hz"),
    ]


def format_summary_text(s: dict) -> str:
    """Plain-text summary for the terminal and logs."""
    lines = [f"── {s.get('name', 'run')}  seed={s.get('seed', '?')}  {s.get('geometry_text', '')}"]
    for k, v in key_metrics(s):
        lines.append(f"  {k:55s} {v}")
    lines.append("  PS PASS/FAIL:")
    for r in s["pass_fail"]:
        val = r["value"]
        vs = fmt(val, 3) if isinstance(val, float) else str(val)
        lines.append(f"    [{verdict(r['pass']):4s}] {r['metric']:42s} {vs:>12s}  "
                     f"({r['threshold']}) {r['note']}")
    return "\n".join(lines)


def _table(ax, rows, col_labels, col_widths=None, colors=None, fontsize=8):
    ax.axis("off")
    t = ax.table(cellText=rows, colLabels=col_labels, loc="upper center", cellLoc="left",
                 colWidths=col_widths)
    t.auto_set_font_size(False)
    t.set_fontsize(fontsize)
    t.scale(1, 1.25)
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor("#CBD5E1")
        if r == 0:
            cell.set_facecolor(NAVY)
            cell.set_text_props(color="white", weight="bold")
        elif colors and (r - 1, c) in colors:
            cell.set_facecolor(colors[(r - 1, c)])
    return t


def _flatten(d: dict, prefix: str = "") -> list[tuple[str, str]]:
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out += _flatten(v, f"{prefix}{k}.")
        else:
            out.append((f"{prefix}{k}", str(v)))
    return out


def write_run_report(path: Path, s: dict, rows: list[dict], timing: list[dict], cfg: dict) -> None:
    """Multi-page PDF: summary + PS table, config, histograms, time series, timeline, FPS."""
    with PdfPages(path) as pdf:
        _page_summary(pdf, s)
        _page_config(pdf, cfg)
        _page_plots(pdf, s, rows, timing)


def _page_summary(pdf, s):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.06, 0.965, "ANANTHAM — Performance Report", fontsize=17, color=NAVY, weight="bold")
    fig.text(0.06, 0.945, f"run '{s.get('name')}'   seed {s.get('seed')}   config "
             f"{s.get('config_hash')}   v{s.get('anantham_version')}   acquisition: "
             f"{s.get('acquisition_mode')}   perception: {s.get('perception_mode')}",
             fontsize=8, color=NAVY)
    fig.text(0.06, 0.93, "Geometry: " + s.get("geometry_text", ""), fontsize=8, color=NAVY)
    if "video" in s:
        v = s["video"]
        fig.text(0.06, 0.915, f"Evaluator MP4: {Path(v['path']).name}  {v['width']}×{v['height']} "
                 f"@ {v['fps']:.2f} fps  spot size {v['spot_size_px']:.2f} px "
                 f"({v['spot_size_source']})", fontsize=8, color=NAVY)
    ax = fig.add_axes([0.04, 0.50, 0.92, 0.40])
    rows, colors = [], {}
    for i, r in enumerate(s["pass_fail"]):
        val = r["value"]
        rows.append([r["metric"], fmt(val, 3) if isinstance(val, float) else str(val),
                     r["threshold"], verdict(r["pass"]), r["note"]])
        colors[(i, 3)] = {"PASS": "#DCFCE7", "FAIL": "#FEE2E2"}.get(verdict(r["pass"]), "#F1F5F9")
    ax.set_title("PS thresholds (SIH26169)", loc="left", color=NAVY, fontsize=11)
    _table(ax, rows, ["Metric", "Measured", "PS requirement", "Result", "Note"],
           [0.36, 0.12, 0.14, 0.08, 0.30], colors)
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.42])
    ax.set_title("Measured metrics (definitions: docs/METRICS.md)", loc="left", color=NAVY,
                 fontsize=11)
    _table(ax, [[k, v] for k, v in key_metrics(s)], ["Metric", "Value"], [0.55, 0.45])
    pdf.savefig(fig)
    plt.close(fig)


def _page_config(pdf, cfg):
    items = _flatten(cfg)
    per = 62
    for start in range(0, len(items), 2 * per):
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.06, 0.965, "Configuration", fontsize=14, color=NAVY, weight="bold")
        for j in range(2):
            chunk = items[start + j * per:start + (j + 1) * per]
            if not chunk:
                continue
            ax = fig.add_axes([0.03 + 0.48 * j, 0.03, 0.46, 0.92])
            _table(ax, [[k, v[:28]] for k, v in chunk], ["Parameter", "Value"], [0.62, 0.38],
                   fontsize=6)
        pdf.savefig(fig)
        plt.close(fig)


def _series(rows, key):
    return np.array([float(r[key]) for r in rows], float)


def state_timeline(ax, t, states):
    """Draw a coloured state strip."""
    order = ["SEARCH", "CANDIDATE", "LOCKED", "COAST", "RECOVER"]
    for st in order:
        m = np.array([s == st for s in states])
        if m.any():
            ax.fill_between(t, 0, 1, where=m, color=STATE_COLORS[st], step="post", label=st,
                            linewidth=0)
    ax.set_yticks([])
    ax.set_xlim(t[0], t[-1] if len(t) > 1 else 1)
    ax.legend(ncol=5, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, 1.6), frameon=False)


def _page_plots(pdf, s, rows, timing):
    t = _series(rows, "t_s")
    ce, te = _series(rows, "centroid_err_px"), _series(rows, "track_err_px")
    locked = np.array([r["state"] == "LOCKED" for r in rows])
    fig, axes = plt.subplots(3, 2, figsize=(8.27, 11.69))
    fig.suptitle("Error distributions and time series", color=NAVY, fontsize=13, weight="bold")
    a = axes[0, 0]
    v = ce[~np.isnan(ce)]
    if v.size:
        a.hist(v, bins=50, color="#0EA5E9")
    a.set_title("Centroiding error histogram", fontsize=9)
    a.set_xlabel("px")
    a = axes[0, 1]
    v = te[locked & ~np.isnan(te)]
    if v.size:
        a.hist(np.clip(v, 0, 50), bins=50, color="#1B2A4A")
    a.axvline(10, color="r", ls="--", lw=1)
    a.set_title("Tracking error histogram (LOCKED, clipped at 50)", fontsize=9)
    a.set_xlabel("px")
    a = axes[1, 0]
    a.plot(t, ce, ".", ms=2, color="#0EA5E9", label="centroiding")
    a.plot(t, np.where(locked, te, np.nan), lw=0.8, color=NAVY, label="tracking (LOCKED)")
    a.axhline(10, color="r", ls="--", lw=1, label="PS 10 px")
    a.set_yscale("symlog", linthresh=1)
    a.set_title("Error vs time", fontsize=9)
    a.set_xlabel("s")
    a.legend(fontsize=7)
    a = axes[1, 1]
    proc = np.array([r["proc_ms"] for r in timing], float)
    fps = 1000.0 / np.maximum(proc, 1e-6)
    a.plot(t, fps, lw=0.5, color="#0EA5E9", label="per frame")
    k = min(30, len(fps))
    if k > 1:
        a.plot(t, np.convolve(fps, np.ones(k) / k, "same"), lw=1.2, color=NAVY, label="1 s mean")
    a.axhline(20, color="r", ls="--", lw=1, label="PS 20 FPS")
    a.set_yscale("log")
    a.set_title("Processing speed (FPS)", fontsize=9)
    a.legend(fontsize=7)
    a = axes[2, 0]
    a.plot(t, _series(rows, "pan_rate_dps"), lw=0.8, label="pan")
    a.plot(t, _series(rows, "tilt_rate_dps"), lw=0.8, label="tilt")
    lim = s.get("rate_limits_dps", [None, None])
    for L in lim[:1]:
        if L:
            a.axhline(L, color="r", ls="--", lw=1, label="±slew limit")
            a.axhline(-L, color="r", ls="--", lw=1)
    a.set_title("Pan / tilt rate (°/s)", fontsize=9)
    a.legend(fontsize=7)
    a = axes[2, 1]
    state_timeline(a, t, [r["state"] for r in rows])
    a.set_title("State timeline", fontsize=9, pad=22)
    a.set_xlabel("s")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    pdf.savefig(fig)
    plt.close(fig)
