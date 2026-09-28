"""Main loop: the ONLY place where the sensor side and the truth side meet.

    source.read()  ──► Frame (image + commanded pointing) ──► PatSystem.process()
         │                                                         │
         └── source.truth() ──► FrameLogger (metrics only)  ◄──── PatOutput

Ground truth flows only to the logger/metrics; the PAT stack never receives it.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from .. import __version__
from ..config import Config, config_hash, save_config, to_dict
from ..io.base import Frame, FrameSource
from ..io.sim_source import SimSource
from ..metrics.logger import FrameLogger
from ..metrics.summary import summarize
from .pat import PatOutput, PatSystem


@dataclass
class StepResult:
    """Everything produced by one loop iteration (for the GUI)."""

    frame: Frame
    out: PatOutput
    truth: dict | None
    row: dict


class Session:
    """Couples a FrameSource with the PAT stack and the logger."""

    def __init__(self, cfg: Config, source: FrameSource, debug: bool = False,
                 spot_size: float | None = None, has_truth: bool = True):
        self.cfg, self.source = cfg, source
        self.pat = PatSystem(cfg, source.geometry, source.fps, source.los_moves_with_command,
                             source.screen_px, spot_size, debug)
        self.logger = FrameLogger()
        self.has_truth = has_truth
        self.wall_start = time.time()
        self.extra: dict = {}

    def step(self) -> StepResult | None:
        """Run one frame of the closed loop; None when the source is exhausted."""
        frame = self.source.read()
        if frame is None:
            return None
        # ══════════════════════════ SENSOR BOUNDARY ══════════════════════════
        # The PAT stack receives ONLY the rendered image(s) and the camera's own
        # commanded pointing. Ground truth never crosses this line.
        out = self.pat.process(frame)
        applied = self.source.command(*out.rate_cmd_deg_s)
        # ══════════════════════════ TRUTH SIDE (metrics) ═════════════════════
        truth = self.source.truth()
        row = self.logger.log(frame, out, truth, applied)
        return StepResult(frame, out, truth, row)

    def run(self, progress=None, dump_dir: Path | None = None, dump_every: int = 0) -> dict:
        """Run until the source ends; returns the summary."""
        while True:
            r = self.step()
            if r is None:
                break
            if dump_dir is not None and dump_every > 0 and r.frame.index % dump_every == 0:
                dump_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(dump_dir / f"{r.frame.index:06d}.png"), r.frame.image)
            if progress is not None:
                progress(r)
        return self.summary()

    def summary(self) -> dict:
        """Compute all PS metrics for the frames processed so far."""
        g = self.source.geometry
        s = summarize(self.logger.rows, self.logger.timing, self.source.fps,
                      min(self.cfg.camera.control_rate_hz, self.source.fps), g.ifov_urad,
                      self.has_truth, self.cfg.target.present)
        s["geometry"] = g.describe(self.source.fps, self.cfg.camera.max_pan_rate_deg_s,
                                   self.cfg.camera.max_tilt_rate_deg_s)
        s["geometry_text"] = g.conversion_text(self.source.fps, self.cfg.camera.max_pan_rate_deg_s,
                                               self.cfg.camera.max_tilt_rate_deg_s)
        s["pat"] = self.pat.describe()
        s["rate_limits_dps"] = [self.cfg.camera.max_pan_rate_deg_s, self.cfg.camera.max_tilt_rate_deg_s]
        s.update({"name": getattr(self, "name", self.cfg.run.name), "seed": self.cfg.run.seed,
                  "config_hash": config_hash(self.cfg), "anantham_version": __version__,
                  "acquisition_mode": self.cfg.acquisition.mode,
                  "perception_mode": self.cfg.perception.mode})
        s.update(self.extra)
        return s

    def write(self, out_dir: str | Path, name: str, pdf: bool = True) -> dict[str, Path]:
        """Write CSVs, summary JSON, config, event log and (optionally) the PDF report."""
        out_dir = Path(out_dir)
        paths = self.logger.write(out_dir, name)
        self.name = name
        summ = self.summary()
        paths["summary"] = out_dir / f"{name}_summary.json"
        with open(paths["summary"], "w", encoding="utf-8") as fh:
            json.dump(_jsonable(summ), fh, indent=2)
        paths["config"] = out_dir / f"{name}_config.yaml"
        save_config(self.cfg, paths["config"])
        paths["log"] = out_dir / f"{name}.log"
        with open(paths["log"], "w", encoding="utf-8") as fh:
            fh.write(f"ANANTHAM {__version__} run '{name}' seed={self.cfg.run.seed} "
                     f"config={config_hash(self.cfg)}\n")
            fh.write(f"geometry: {summ['geometry_text']}\n")
            fh.write(f"pat: {json.dumps(_jsonable(summ['pat']))}\n")
            for e in self.logger.events:
                fh.write(e + "\n")
        if pdf:
            from ..metrics.report import write_run_report

            paths["report"] = out_dir / f"{name}_report.pdf"
            write_run_report(paths["report"], summ, self.logger.rows, self.logger.timing,
                             to_dict(self.cfg))
        return paths


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None if math.isnan(o) else ("inf" if o > 0 else "-inf")
    if hasattr(o, "item"):
        return o.item()
    return o


def run_simulation(cfg: Config, out_dir: str | Path | None = None, name: str | None = None,
                   pdf: bool = True, progress=None) -> tuple[dict, dict]:
    """Run a full simulation; returns (summary, written paths)."""
    src = SimSource(cfg)
    sess = Session(cfg, src)
    sess.name = name or cfg.run.name
    dump = Path(out_dir) / f"{name or cfg.run.name}_dump" if (out_dir and cfg.run.dump_every) else None
    sess.run(progress, dump, cfg.run.dump_every)
    paths = sess.write(out_dir, name or cfg.run.name, pdf) if out_dir else {}
    return sess.summary(), paths


def run_video(cfg: Config, video: str | Path, truth_csv: str | Path | None = None,
              out_dir: str | Path | None = None, name: str | None = None, pdf: bool = True,
              scale_frames: int = 15, progress=None) -> tuple[dict, dict]:
    """Evaluator MP4 mode: adaptive scale, then the same PAT stack on the video."""
    from ..io.video_source import VideoSource
    from ..perception.scale import estimate_spot_scale
    from .pat import expected_spot_size

    src = VideoSource(video, cfg, truth_csv)
    if cfg.perception.expected_size_px:
        size, est = float(cfg.perception.expected_size_px), None
    else:
        est = estimate_spot_scale(src.peek(scale_frames), cfg.perception, expected_spot_size(cfg))
        size = est.size_px
    sess = Session(cfg, src, spot_size=size, has_truth=truth_csv is not None)
    sess.extra["video"] = {"path": str(video), "width": src.width, "height": src.height,
                           "fps": src.fps, "frames_reported": src.n_frames,
                           "spot_size_px": size,
                           "spot_size_source": "user" if est is None else
                           ("default (no blob found)" if est.fallback else
                            f"adaptive ({est.n_frames_with_blob}/{est.n_frames_used} frames)")}
    sess.run(progress)
    src.close()
    paths = sess.write(out_dir, name or Path(video).stem, pdf) if out_dir else {}
    return sess.summary(), paths
