"""Command-line interface.

    anantham gui
    anantham run --preset circular --seed 3 --duration 20 --out results/
    anantham video --input eval.mp4 [--truth truth.csv] --out results/
    anantham bench --scenarios all --seeds 5 --out results/ [--ablation]
    anantham make-video --preset fog --out test.mp4        (writes truth CSV too)
    anantham train --out anantham/models/                  (CNN dataset + training + ONNX)
    anantham presets                                       (regenerate preset YAMLs)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import __version__
from .config import Config, load_config, merge, validate


def _parse_set(items: list[str] | None) -> dict:
    """``a.b=c`` strings → nested override dict (values parsed as YAML)."""
    out: dict = {}
    for it in items or []:
        key, _, val = it.partition("=")
        d = out
        parts = key.strip().split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = yaml.safe_load(val)
    return out


def _prepare(args) -> Config:
    cfg = load_config(args.preset)
    cfg = merge(cfg, _parse_set(getattr(args, "set", None)))
    if getattr(args, "seed", None) is not None:
        cfg.run.seed = args.seed
    if getattr(args, "duration", None) is not None:
        cfg.run.duration_s = args.duration
    if getattr(args, "acq", None):
        cfg.acquisition.mode = args.acq
    if getattr(args, "start", None):
        cfg.target.start = args.start
    if getattr(args, "perception", None):
        cfg.perception.mode = args.perception
    if getattr(args, "dump_every", None):
        cfg.run.dump_every = args.dump_every
    issues = validate(cfg)
    errors = [i for i in issues if i.severity == "error"]
    ps_issues = [i for i in issues if i.severity == "ps"]
    for i in issues:
        print(i, file=sys.stderr)
    if errors or (ps_issues and not getattr(args, "allow_out_of_spec", False)):
        raise SystemExit("configuration rejected (use --allow-out-of-spec for PS-range issues)")
    return cfg


def _print_summary(s: dict) -> None:
    from .metrics.report import format_summary_text

    print(format_summary_text(s))


def cmd_run(args) -> None:
    """Run one simulation and write logs + report."""
    from .pipeline.session import run_simulation

    cfg = _prepare(args)
    name = args.name or f"{Path(str(args.preset)).stem}_s{cfg.run.seed}"
    s, paths = run_simulation(cfg, args.out, name, pdf=not args.no_pdf)
    _print_summary(s)
    for k, p in paths.items():
        print(f"  {k:9s} {p}")


def cmd_video(args) -> None:
    """Evaluator MP4 mode."""
    from .pipeline.session import run_video

    cfg = _prepare(args)
    s, paths = run_video(cfg, args.input, args.truth, args.out, args.name, pdf=not args.no_pdf,
                         scale_frames=args.scale_frames)
    print(json.dumps(s.get("video", {}), indent=2))
    _print_summary(s)
    for k, p in paths.items():
        print(f"  {k:9s} {p}")


def cmd_bench(args) -> None:
    """Benchmark matrix (and optional ablation)."""
    from .bench.run_bench import main_bench

    main_bench(args)


def cmd_make_video(args) -> None:
    """Synthetic evaluator-style MP4 + truth CSV."""
    from .tools_video import make_test_video

    cfg = _prepare(args)
    info = make_test_video(cfg, args.out, fixed_camera=not args.moving_camera,
                           realism=not args.ideal)
    print(json.dumps(info, indent=2))


def cmd_gui(args) -> None:
    """Launch the PyQt6 console."""
    from .gui.app import main as gui_main

    extra = []
    if args.screenshot:
        extra = ["--screenshot", args.screenshot, "--seconds", str(args.seconds), "--preset",
                 args.preset, "--size", args.size, "--tab", args.tab]
    gui_main(extra)


def cmd_train(args) -> None:
    """Build the dataset, train the CNN and export ONNX."""
    from .training.train_cnn import main_train

    main_train(args)


def cmd_presets(args) -> None:
    """Regenerate config/presets/*.yaml from bench/scenarios.py."""
    from .bench.presets import write_presets

    for p in write_presets():
        print(p)


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for all sub-commands."""
    ap = argparse.ArgumentParser(prog="anantham", description="ANANTHAM FSOC coarse PAT lab")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    def common(p, default_preset="default"):
        p.add_argument("--preset", default=default_preset, help="preset name or YAML path")
        p.add_argument("--set", action="append", help="override, e.g. target.size_px=12")
        p.add_argument("--seed", type=int)
        p.add_argument("--allow-out-of-spec", action="store_true")
        p.add_argument("--perception", choices=["classical", "hybrid", "cnn"])

    p = sub.add_parser("gui", help="launch the GUI")
    p.add_argument("--screenshot", help="(dev) run, save a window screenshot and exit")
    p.add_argument("--seconds", type=float, default=6.0)
    p.add_argument("--preset", default="default")
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--tab", default="Tracking")
    p.set_defaults(fn=cmd_gui)

    p = sub.add_parser("run", help="run one simulation")
    common(p)
    p.add_argument("--duration", type=float)
    p.add_argument("--out", default="results")
    p.add_argument("--name")
    p.add_argument("--acq", choices=["spiral", "wide_fov"])
    p.add_argument("--start", choices=["random", "centre", "in_fov", "user"])
    p.add_argument("--dump-every", type=int, default=0, help="save every N-th frame as PNG")
    p.add_argument("--no-pdf", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("video", help="evaluator MP4 mode (bypass the PTZ camera)")
    common(p)
    p.add_argument("--input", required=True)
    p.add_argument("--truth")
    p.add_argument("--out", default="results")
    p.add_argument("--name")
    p.add_argument("--scale-frames", type=int, default=15)
    p.add_argument("--no-pdf", action="store_true")
    p.set_defaults(fn=cmd_video)

    p = sub.add_parser("bench", help="benchmark scenarios")
    p.add_argument("--scenarios", default="all", help="all | core | extra | comma list")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--out", default="results/bench")
    p.add_argument("--acq", default="spiral", help="spiral | wide_fov | both")
    p.add_argument("--start", default="random", help="random | in_fov | both")
    p.add_argument("--perception", default=None)
    p.add_argument("--ablation", action="store_true")
    p.add_argument("--ablation-seeds", type=int, default=3)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--smoke", action="store_true", help="10-second CI smoke benchmark")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("make-video", help="synthetic evaluator MP4 + truth CSV")
    common(p)
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--out", required=True)
    p.add_argument("--moving-camera", action="store_true",
                   help="record the closed-loop PTZ view instead of a fixed camera")
    p.add_argument("--ideal", action="store_true",
                   help="no PSF mismatch (renderer model = centroid model)")
    p.set_defaults(fn=cmd_make_video)

    p = sub.add_parser("train", help="train the CNN verifier and export ONNX")
    p.add_argument("--out", default=str(Path(__file__).parent / "models"))
    p.add_argument("--samples", type=int, default=60000)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_train)

    sub.add_parser("presets", help="regenerate preset YAMLs").set_defaults(fn=cmd_presets)
    return ap


def main(argv: list[str] | None = None) -> None:
    """Entry point. With no arguments the GUI starts (frozen .exe behaviour)."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["gui"]
    args = build_parser().parse_args(argv)
    if not hasattr(args, "fn"):
        build_parser().print_help()
        return
    args.fn(args)


if __name__ == "__main__":
    main()
