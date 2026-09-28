"""Insert measured results into README.md and docs/TECHNICAL_REPORT.md (R2: no hand-typed numbers).

Replaces the content between markers ``<!-- RESULTS:<key> -->`` and ``<!-- /RESULTS:<key> -->``
with tables generated from a benchmark directory:

    python tools/insert_results.py results/final

Keys: bench_headline, bench_spiral_random, bench_spiral_in_fov, bench_wide_random,
bench_wide_in_fov, ablation, cnn, worst, meta.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def f(v, nd=2, pct=False):
    """Format for Markdown ('—' = not measured)."""
    x = _num(v)
    if x is None:
        return "—"
    if math.isinf(x):
        return "∞"
    return f"{100 * x:.{nd}f} %" if pct else f"{x:.{nd}f}"


def load_csv(p: Path) -> list[dict]:
    """Read a CSV into dicts."""
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def group_table(agg: list[dict], acq: str, start: str) -> str:
    """Scenario matrix for one (acq, start) group."""
    rows = [a for a in agg if a["acq"] == acq and a["start"] == start and a["variant"] == "full"]
    if not rows:
        return "_not yet measured_\n"
    s = ("| scenario | acquired | acq. time s mean / worst | centroid RMSE px (worst) | "
         "track RMSE all px mean / worst | track RMSE steady px mean / worst | "
         "target loss mean / worst | re-acq max s | re-acq after visible max s | unrec. | "
         "false-lock fr. | proc FPS min | all-PS pass |\n|" + "---|" * 13 + "\n")
    for a in rows:
        s += (f"| {a['scenario']} | {a['acquired']}/{a['seeds']} | {f(a['acq_time_s_mean'])} / "
              f"{f(a['acq_time_s_worst'])} | {f(a['cent_rmse_px_worst'], 3)} | "
              f"{f(a['trk_rmse_px_mean'])} / {f(a['trk_rmse_px_worst'])} | "
              f"{f(a['trk_ss_rmse_px_mean'])} / {f(a['trk_ss_rmse_px_worst'])} | "
              f"{f(a['target_loss_mean'], 2, True)} / {f(a['target_loss_worst'], 2, True)} | "
              f"{f(a['reacq_max_s_worst'])} | {f(a['reacq_max_after_visible_s_worst'])} | "
              f"{a['unrecovered']} | "
              f"{f(a['false_lock_frames_worst'], 0)} | {f(a['proc_fps_worst'], 0)} | "
              f"{f(a['pass_rate'], 0, True)} |\n")
    return s


def headline(runs: list[dict]) -> str:
    """Per-PS-row pass counts over all benchmark runs, split by acquisition/start."""
    keys = [("pass_acq", "Acquisition ≤ 2 s"), ("pass_cent", "Centroiding RMSE ≤ 10 px"),
            ("pass_trk", "Tracking RMSE (all locked) ≤ 10 px"),
            ("pass_trk_ss", "Tracking RMSE (steady) ≤ 10 px"), ("pass_loss", "Target loss < 5 %"),
            ("pass_reacq", "Re-acquisition ≤ 1 s"), ("pass_fps", "Processing ≥ 20 FPS"),
            ("pass_absent", "No false lock (target absent)"), ("pass_all", "All rows pass")]
    groups = sorted({(r["acq"], r["start"]) for r in runs})
    s = "| PS requirement | " + " | ".join(f"{a} / {st}" for a, st in groups) + " |\n"
    s += "|---|" + "---|" * len(groups) + "\n"
    for k, label in keys:
        cells = []
        for g in groups:
            vals = [r[k] for r in runs if (r["acq"], r["start"]) == g and r[k] not in ("", "None")]
            ok = sum(v == "True" for v in vals)
            cells.append(f"{ok}/{len(vals)}" if vals else "n/a")
        s += f"| {label} | " + " | ".join(cells) + " |\n"
    return s


def ablation(path: Path) -> str:
    """Ablation table (Markdown file written by the bench)."""
    return path.read_text(encoding="utf-8") if path.exists() else "_not yet measured_\n"


def cnn_card() -> str:
    """CNN validation metrics from the model card."""
    p = ROOT / "anantham" / "models" / "verifier_card.json"
    if not p.exists():
        return "_not yet measured_\n"
    c = json.loads(p.read_text(encoding="utf-8"))
    m = c["final"]
    return (f"| item | value |\n|---|---|\n| training samples (simulated ROIs) | {c['n_samples']} "
            f"(10 % held out) |\n| epochs / seed | {c['epochs']} / {c['seed']} |\n"
            f"| parameters | {c['params']} |\n"
            f"| validation accuracy | {100 * m['accuracy']:.2f} % |\n"
            f"| precision / recall | {100 * m['precision']:.2f} % / {100 * m['recall']:.2f} % |\n"
            f"| false-positive rate | {100 * m['false_positive_rate']:.2f} % |\n"
            f"| heatmap localisation error median / P95 | "
            f"{m['heatmap_loc_err_px_median']:.3f} / {m['heatmap_loc_err_px_p95']:.3f} px |\n"
            f"| training time (CPU) | {c['train_time_s'] / 60:.1f} min |\n")


def worst(agg: list[dict]) -> str:
    """Five worst scenario groups by pass rate / loss / steady error."""
    pres = [a for a in agg if a["scenario"] != "target_absent" and a["variant"] == "full"]
    pres.sort(key=lambda a: (_num(a["pass_rate"]) or 0, -(_num(a["target_loss_worst"]) or 0),
                             -(_num(a["trk_ss_rmse_px_worst"]) or 0)))
    s = ("| scenario | acq / start | pass rate | worst steady RMSE px | worst loss | "
         "worst acq. s |\n|---|---|---|---|---|---|\n")
    for a in pres[:8]:
        s += (f"| {a['scenario']} | {a['acq']} / {a['start']} | {f(a['pass_rate'], 0, True)} | "
              f"{f(a['trk_ss_rmse_px_worst'])} | {f(a['target_loss_worst'], 2, True)} | "
              f"{f(a['acq_time_s_worst'])} |\n")
    return s


def replace(text: str, key: str, body: str) -> str:
    """Replace a marker block."""
    pat = re.compile(rf"(<!-- RESULTS:{key} -->\n).*?(<!-- /RESULTS:{key} -->)", re.S)
    return pat.sub(lambda m: m.group(1) + body + m.group(2), text)


def main(bench_dir: str) -> None:
    """Fill every marker in README.md and docs/TECHNICAL_REPORT.md."""
    d = Path(bench_dir)
    agg = load_csv(d / "benchmark_summary.csv")
    runs = load_csv(d / "benchmark_runs.csv")
    meta = json.loads((d / "benchmark_meta.json").read_text(encoding="utf-8"))
    blocks = {
        "meta": (f"Source: `{d.as_posix()}` — {meta['runs']} runs, {meta['seeds']} seeds × "
                 f"{meta['duration_s']:g} s, acquisition modes {', '.join(meta['acq'])}, start modes "
                 f"{', '.join(meta['starts'])}, perception: {meta['perception']}"
                 + (f"; ablation {meta['ablation_runs']} runs" if "ablation_runs" in meta else "")
                 + ".\n"),
        "bench_headline": headline(runs),
        "bench_spiral_random": group_table(agg, "spiral", "random"),
        "bench_spiral_in_fov": group_table(agg, "spiral", "in_fov"),
        "bench_wide_random": group_table(agg, "wide_fov", "random"),
        "bench_wide_in_fov": group_table(agg, "wide_fov", "in_fov"),
        "ablation": ablation(d / "ablation_summary.md"),
        "cnn": cnn_card(),
        "worst": worst(agg),
    }
    for doc in (ROOT / "README.md", ROOT / "docs" / "TECHNICAL_REPORT.md"):
        if not doc.exists():
            continue
        t = doc.read_text(encoding="utf-8")
        for k, v in blocks.items():
            t = replace(t, k, v)
        doc.write_text(t, encoding="utf-8")
        print(f"updated {doc}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/final")
