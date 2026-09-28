"""Benchmark runner: scenarios × seeds × acquisition modes × start modes (× ablation variants).

Every run writes its own ``*_frames.csv``, ``*_summary.json`` and config, so any number in
the aggregated tables can be traced back to a run. Outputs:

* ``benchmark_runs.csv``     one row per run
* ``benchmark_summary.csv``  mean and worst per scenario / mode (and ``.md``)
* ``benchmark_report.pdf``   scenario matrix with PASS/FAIL colouring, worst case highlighted
* ``ablation_*.csv/.md``     component effects (``--ablation``)
"""

from __future__ import annotations

import csv
import json
import math
import os
import time
from multiprocessing import get_context
from pathlib import Path

import numpy as np

from .scenarios import ABLATION, CORE, EXTRA, SCENARIOS, scenario_config

RUN_FIELDS = [
    "scenario", "seed", "acq", "start", "variant", "acquired", "acq_time_s", "cent_rmse_px",
    "cent_p95_px", "cent_rmse_urad", "trk_rmse_px", "trk_ss_rmse_px", "trk_ss_p95_px",
    "trk_ss_ctrl_rmse_px", "retention", "target_loss", "coverage", "reacq_count", "reacq_max_s",
    "reacq_max_after_visible_s", "unrecovered", "wrong_target_frames", "false_lock_frames",
    "locked_frames", "proc_fps", "proc_ms_p95", "pass_acq", "pass_cent", "pass_trk",
    "pass_trk_ss", "pass_loss", "pass_reacq", "pass_fps", "pass_absent", "pass_all",
    "worst_case_search_s",
]


def _pass(summary: dict, metric_prefix: str):
    for r in summary["pass_fail"]:
        if r["metric"].startswith(metric_prefix):
            return r["pass"]
    return None


def row_from_summary(s: dict, scenario: str, seed: int, acq: str, start: str, variant: str) -> dict:
    """Flatten a run summary into one benchmark row."""
    ce, ra = s["centroiding_error_px"], s["reacquisition"]
    pf = [r["pass"] for r in s["pass_fail"]]
    return {
        "scenario": scenario, "seed": seed, "acq": acq, "start": start, "variant": variant,
        "acquired": int(s["acquired"]), "acq_time_s": s["acquisition_time_s"],
        "cent_rmse_px": ce["rmse"], "cent_p95_px": ce["p95"], "cent_rmse_urad": ce.get("rmse_urad"),
        "trk_rmse_px": s["tracking_error_px"]["rmse"],
        "trk_ss_rmse_px": s["tracking_error_steady_px"]["rmse"],
        "trk_ss_p95_px": s["tracking_error_steady_px"]["p95"],
        "trk_ss_ctrl_rmse_px": s["tracking_error_steady_ctrl_px"]["rmse"],
        "retention": s["lock_retention"], "target_loss": s["target_loss"],
        "coverage": s["detection_coverage"], "reacq_count": ra["count"], "reacq_max_s": ra["max_s"],
        "reacq_max_after_visible_s": ra["max_after_visible_s"],
        "unrecovered": int(ra["unrecovered_at_end"]),
        "wrong_target_frames": s["wrong_target_locked_frames"],
        "false_lock_frames": s["false_lock_frames"], "locked_frames": s["locked_frames"],
        "proc_fps": s["processing_fps"], "proc_ms_p95": s["processing_ms"]["p95"],
        "pass_acq": _pass(s, "Acquisition"), "pass_cent": _pass(s, "Centroiding"),
        "pass_trk": _pass(s, "Tracking error (RMSE, all"),
        "pass_trk_ss": _pass(s, "Tracking error (RMSE, steady"), "pass_loss": _pass(s, "Target loss"),
        "pass_reacq": _pass(s, "Re-acquisition"), "pass_fps": _pass(s, "Processing"),
        "pass_absent": _pass(s, "No false lock"),
        "pass_all": all(p is not False for p in pf),
        "worst_case_search_s": s["pat"]["worst_case_spiral_search_s"],
    }


def _job(args: tuple) -> dict:
    scenario, seed, acq, start, variant, duration, out_dir, perception = args
    import cv2

    cv2.setNumThreads(1)
    from ..pipeline.session import run_simulation

    extra = {"acquisition": {"mode": acq}, "run": {"duration_s": duration}}
    cfg = scenario_config(scenario, seed, extra=extra)
    if variant != "full":
        from ..config import merge

        cfg = merge(cfg, ABLATION[variant])
    if perception:
        cfg.perception.mode = perception
    if SCENARIOS[scenario].get("target", {}).get("start") is None:
        cfg.target.start = start
    name = f"{scenario}_{acq}_{start}_{variant}_s{seed}"
    t0 = time.time()
    s, _ = run_simulation(cfg, out_dir, name, pdf=False)
    row = row_from_summary(s, scenario, seed, acq, start, variant)
    row["wall_s"] = time.time() - t0
    return row


def run_jobs(jobs: list[tuple], workers: int, label: str = "") -> list[dict]:
    """Run jobs in a process pool with a progress line."""
    rows = []
    t0 = time.time()
    workers = workers or max(os.cpu_count() or 1, 1)
    ctx = get_context("spawn" if os.name == "nt" else "fork")
    with ctx.Pool(workers) as pool:
        for i, r in enumerate(pool.imap_unordered(_job, jobs), 1):
            rows.append(r)
            el = time.time() - t0
            print(f"\r{label} {i}/{len(jobs)}  {el:6.0f}s elapsed, ~{el / i * (len(jobs) - i):6.0f}s left",
                  end="", flush=True)
    print()
    rows.sort(key=lambda r: (r["variant"], r["scenario"], r["acq"], r["start"], r["seed"]))
    return rows


def _nanmean(v):
    a = np.array([np.nan if x is None else float(x) for x in v], float)
    a = a[~np.isnan(a)]
    return float(a.mean()) if a.size else float("nan")


def _nanworst(v, hi=True):
    a = np.array([np.nan if x is None else float(x) for x in v], float)
    a = a[~np.isnan(a)]
    if not a.size:
        return float("nan")
    return float(a.max() if hi else a.min())


AGG = [  # (column, higher_is_worse)
    ("acq_time_s", True), ("cent_rmse_px", True), ("trk_rmse_px", True), ("trk_ss_rmse_px", True),
    ("trk_ss_ctrl_rmse_px", True), ("target_loss", True), ("coverage", False),
    ("reacq_max_s", True), ("wrong_target_frames", True), ("false_lock_frames", True),
    ("proc_fps", False),
]


def aggregate(rows: list[dict]) -> list[dict]:
    """Mean and worst over seeds per (variant, scenario, acq, start)."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["variant"], r["scenario"], r["acq"], r["start"]), []).append(r)
    out = []
    for (variant, sc, acq, start), g in groups.items():
        a = {"variant": variant, "scenario": sc, "acq": acq, "start": start, "seeds": len(g),
             "acquired": sum(r["acquired"] for r in g),
             "unrecovered": sum(r["unrecovered"] for r in g),
             "pass_rate": sum(bool(r["pass_all"]) for r in g) / len(g)}
        for col, hi in AGG:
            a[f"{col}_mean"] = _nanmean([r[col] for r in g])
            a[f"{col}_worst"] = _nanworst([r[col] for r in g], hi)
        for p in ("pass_acq", "pass_cent", "pass_trk", "pass_trk_ss", "pass_loss", "pass_reacq",
                  "pass_fps", "pass_absent"):
            vals = [r[p] for r in g if r[p] is not None]
            a[p] = (sum(bool(v) for v in vals) / len(vals)) if vals else None
        out.append(a)
    order = {n: i for i, n in enumerate(SCENARIOS)}
    out.sort(key=lambda a: (a["variant"], a["acq"], a["start"], order.get(a["scenario"], 99)))
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    """Write dict rows to CSV (NaN → 'nan')."""
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt_csv(r.get(k)) for k in fields})


def _fmt_csv(v):
    if isinstance(v, float):
        return "nan" if math.isnan(v) else ("inf" if math.isinf(v) else f"{v:.6g}")
    return v


def f2(v, nd=2, pct=False):
    """Markdown number formatting."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return f"{100 * v:.{nd}f}%" if pct else f"{v:.{nd}f}"


def markdown_table(agg: list[dict]) -> str:
    """Scenario matrix as Markdown (mean / worst over seeds)."""
    hdr = ("| scenario | acq | start | seeds | acquired | acq time s (mean/worst) | "
           "centroid RMSE px (mean/worst) | track RMSE all px (mean/worst) | "
           "track RMSE steady px (mean/worst) | target loss (mean/worst) | "
           "re-acq max s (worst) | unrecovered | wrong-target frames (worst) | "
           "proc FPS (mean/min) | all-PS pass rate |\n")
    hdr += "|" + "---|" * 15 + "\n"
    lines = []
    for a in agg:
        lines.append(
            f"| {a['scenario']} | {a['acq']} | {a['start']} | {a['seeds']} | {a['acquired']} | "
            f"{f2(a['acq_time_s_mean'])} / {f2(a['acq_time_s_worst'])} | "
            f"{f2(a['cent_rmse_px_mean'], 3)} / {f2(a['cent_rmse_px_worst'], 3)} | "
            f"{f2(a['trk_rmse_px_mean'])} / {f2(a['trk_rmse_px_worst'])} | "
            f"{f2(a['trk_ss_rmse_px_mean'])} / {f2(a['trk_ss_rmse_px_worst'])} | "
            f"{f2(a['target_loss_mean'], 2, True)} / {f2(a['target_loss_worst'], 2, True)} | "
            f"{f2(a['reacq_max_s_worst'])} | {a['unrecovered']} | "
            f"{f2(a['wrong_target_frames_worst'], 0)} | "
            f"{f2(a['proc_fps_mean'], 0)} / {f2(a['proc_fps_worst'], 0)} | "
            f"{f2(a['pass_rate'], 0, True)} |")
    return hdr + "\n".join(lines) + "\n"


def select_scenarios(spec: str) -> list[str]:
    """'all' | 'core' | 'extra' | 'motion' | comma list."""
    if spec == "all":
        return list(SCENARIOS)
    if spec == "core":
        return CORE
    if spec == "extra":
        return EXTRA
    if spec == "motion":
        return CORE[:8]
    names = [s.strip() for s in spec.split(",") if s.strip()]
    for n in names:
        if n not in SCENARIOS:
            raise SystemExit(f"unknown scenario '{n}'")
    return names


def main_bench(args) -> None:
    """CLI entry (``anantham bench``)."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.smoke:
        args.scenarios, args.seeds, args.duration = "circular,salt_pepper", 1, 5.0
        args.acq, args.start = "spiral", "in_fov"
    scen = select_scenarios(args.scenarios)
    acqs = ["spiral", "wide_fov"] if args.acq == "both" else [args.acq]
    starts = ["random", "in_fov"] if args.start == "both" else [args.start]
    runs_dir = out / "runs"
    t0 = time.time()
    jobs = [(sc, seed, acq, st, "full", args.duration, runs_dir, args.perception)
            for sc in scen for acq in acqs for st in starts for seed in range(args.seeds)]
    rows = run_jobs(jobs, args.workers, "bench")
    agg = aggregate(rows)
    write_csv(out / "benchmark_runs.csv", rows)
    write_csv(out / "benchmark_summary.csv", agg)
    md = markdown_table(agg)
    (out / "benchmark_summary.md").write_text(md, encoding="utf-8")
    meta = {"scenarios": scen, "seeds": args.seeds, "duration_s": args.duration, "acq": acqs,
            "starts": starts, "perception": args.perception or "config default",
            "runs": len(rows), "wall_s": time.time() - t0}
    if args.ablation:
        ab_jobs = [(sc, seed, "spiral", "in_fov", v, args.duration, out / "ablation_runs", None)
                   for v in ABLATION for sc in scen for seed in range(args.ablation_seeds)]
        ab_rows = run_jobs(ab_jobs, args.workers, "ablation")
        write_csv(out / "ablation_runs.csv", ab_rows)
        ab = ablation_table(ab_rows)
        write_csv(out / "ablation_summary.csv", ab)
        (out / "ablation_summary.md").write_text(ablation_markdown(ab), encoding="utf-8")
        meta["ablation_runs"] = len(ab_rows)
    (out / "benchmark_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    from ..metrics.report import write_bench_report

    write_bench_report(out / "benchmark_report.pdf", agg, rows, meta)
    print(md)
    print(f"wrote {out}")


def ablation_table(rows: list[dict]) -> list[dict]:
    """Per-variant averages over all scenarios and seeds."""
    out = []
    for v in ABLATION:
        g = [r for r in rows if r["variant"] == v]
        if not g:
            continue
        present = [r for r in g if r["scenario"] != "target_absent"]
        absent = [r for r in g if r["scenario"] == "target_absent"]
        out.append({
            "variant": v, "runs": len(g),
            "acquired_frac": sum(r["acquired"] for r in present) / max(len(present), 1),
            "cent_rmse_px": _nanmean([r["cent_rmse_px"] for r in present]),
            "trk_ss_rmse_px": _nanmean([r["trk_ss_rmse_px"] for r in present]),
            "trk_ss_rmse_worst": _nanworst([r["trk_ss_rmse_px"] for r in present]),
            "target_loss": _nanmean([r["target_loss"] for r in present]),
            "target_loss_worst": _nanworst([r["target_loss"] for r in present]),
            "reacq_count": _nanmean([r["reacq_count"] for r in present]),
            "reacq_max_s": _nanworst([r["reacq_max_s"] for r in present]),
            "unrecovered_runs": sum(r["unrecovered"] for r in present),
            "wrong_target_frames": _nanmean([r["wrong_target_frames"] for r in present]),
            "false_lock_absent_frames": _nanmean([r["locked_frames"] for r in absent]) if absent
            else float("nan"),
            "proc_fps": _nanmean([r["proc_fps"] for r in g]),
            "pass_rate": sum(bool(r["pass_all"]) for r in g) / len(g),
        })
    return out


def ablation_markdown(ab: list[dict]) -> str:
    """Ablation table as Markdown."""
    s = ("| variant | runs | acquired | centroid RMSE px | steady track RMSE px (mean/worst) | "
         "target loss (mean/worst) | re-acq events/run | re-acq max s | unrecovered runs | "
         "wrong-target frames/run | false-lock frames (target absent) | proc FPS | all-PS pass |\n")
    s += "|" + "---|" * 13 + "\n"
    for a in ab:
        s += (f"| {a['variant']} | {a['runs']} | {f2(a['acquired_frac'], 0, True)} | "
              f"{f2(a['cent_rmse_px'], 3)} | {f2(a['trk_ss_rmse_px'])} / {f2(a['trk_ss_rmse_worst'])} | "
              f"{f2(a['target_loss'], 2, True)} / {f2(a['target_loss_worst'], 2, True)} | "
              f"{f2(a['reacq_count'], 1)} | {f2(a['reacq_max_s'])} | {a['unrecovered_runs']} | "
              f"{f2(a['wrong_target_frames'], 1)} | {f2(a['false_lock_absent_frames'], 1)} | "
              f"{f2(a['proc_fps'], 0)} | {f2(a['pass_rate'], 0, True)} |\n")
    return s
