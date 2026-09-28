"""Background workers: the closed loop runs in a QThread and emits display packets.

Rendering/display cost never enters "processing time": processing time is measured
inside :meth:`PatSystem.process` only.
"""

from __future__ import annotations

import copy
import time
import traceback

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..config import Config
from ..metrics.summary import summarize


def _build_session(cfg: Config, video: str | None, truth: str | None, debug: bool):
    """Create the Session (runs inside the loop process)."""
    from ..pipeline.session import Session

    if video:
        from ..io.video_source import VideoSource
        from ..perception.scale import estimate_spot_scale
        from ..pipeline.pat import expected_spot_size

        src = VideoSource(video, cfg, truth)
        est = estimate_spot_scale(src.peek(15), cfg.perception, expected_spot_size(cfg))
        sess = Session(cfg, src, debug=debug, spot_size=est.size_px, has_truth=truth is not None)
        sess.extra["video"] = {"path": video, "width": src.width, "height": src.height,
                               "fps": src.fps, "frames_reported": src.n_frames,
                               "spot_size_px": est.size_px,
                               "spot_size_source": "default (no blob found)" if est.fallback
                               else f"adaptive ({est.n_frames_with_blob}/{est.n_frames_used})"}
    else:
        from ..io.sim_source import SimSource

        sess = Session(cfg, SimSource(cfg), debug=debug)
    sess.name = cfg.run.name
    return sess


def _metrics(sess, cfg: Config) -> dict | None:
    if not sess.logger.rows:
        return None
    return summarize(sess.logger.rows, sess.logger.timing, sess.source.fps,
                     min(cfg.camera.control_rate_hz, sess.source.fps),
                     sess.source.geometry.ifov_urad, sess.has_truth, cfg.target.present)


def _packet(sess, r, metrics, debug: bool) -> dict:
    o, f = r.out, r.frame
    b = None
    if r.truth:
        for bb in r.truth.get("beacons", []):
            if bb.get("designated"):
                b = bb
    others = [(bb["app_x"], bb["app_y"]) for bb in (r.truth or {}).get("beacons", [])
              if not bb.get("designated") and bb.get("in_fov")]
    return {
        "kind": "frame", "k": f.index, "t": f.t, "image": np.ascontiguousarray(f.image),
        "state": o.state, "mode": o.mode, "meas": o.meas_img, "pred": o.pred_img,
        "vel": o.vel_ptg, "ellipse": o.ellipse, "sigma": o.sigma, "gate": o.gate,
        "cands": [(c.x, c.y, c.accepted and not c.reason.startswith(("size", "edge", "low",
                                                                      "rejected", "cnn")),
                   c.as_row()) for c in o.candidates],
        "truth": None if b is None or not b.get("visible") else (b["app_x"], b["app_y"]),
        "truth_screen": None if b is None else (b.get("screen_u"), b.get("screen_v")),
        "distractors": others,
        "bore_px": f.bore_px, "pointing_deg": f.pointing_deg, "rate": r.row["pan_rate_dps"],
        "rate_t": r.row["tilt_rate_dps"], "proc_ms": o.proc_ms, "snr": o.snr,
        "centroid_err": r.row["centroid_err_px"], "track_err": r.row["track_err_px"],
        "search_target": o.search_target, "pred_ptg": o.pred_ptg,
        "debug": o.debug if debug else {}, "metrics": metrics,
        "n_frames": sess.source.n_frames, "fps": sess.source.fps,
    }


def loop_process(cfg: Config, video, truth, speed: float, debug: bool, cmd_q, out_q) -> None:
    """Closed loop in its own process (no GIL contention with Qt painting).

    Commands on ``cmd_q``: ("pause", bool) ("step",) ("speed", x) ("debug", bool)
    ("export", out_dir, name) ("stop",). Messages on ``out_q``: info / frame / export /
    finished / error dicts. Frame packets are dropped (never queued up) when the GUI is slow;
    the simulation itself never waits for the display.
    """
    import multiprocessing as mp
    import queue

    parent = mp.parent_process()

    def put(msg: dict) -> bool:
        """Blocking put that gives up when the GUI process is gone."""
        while parent is None or parent.is_alive():
            try:
                out_q.put(msg, timeout=0.5)
                return True
            except queue.Full:
                continue
        return False

    try:
        sess = _build_session(cfg, video, truth, debug)
        put({"kind": "info", "pat": sess.pat.describe(),
                   "geometry": sess.source.geometry.conversion_text(
                       sess.source.fps, cfg.camera.max_pan_rate_deg_s, cfg.camera.max_tilt_rate_deg_s),
                   "video": sess.extra.get("video"),
                   "search_path": None if sess.pat.global_search is None else
                   [p.tolist() for p in sess.pat.global_search.points]})
        period = 1.0 / sess.source.fps
        paused, step, done, stop = False, False, False, False
        last_emit, last_metrics, metrics = 0.0, 0.0, None
        t_next = time.perf_counter()
        while not stop:
            if parent is not None and not parent.is_alive():
                break
            try:
                while True:
                    c = cmd_q.get_nowait()
                    if c[0] == "pause":
                        paused = c[1]
                    elif c[0] == "step":
                        step = True
                    elif c[0] == "speed":
                        speed = c[1]
                    elif c[0] == "debug":
                        debug = c[1]
                    elif c[0] == "stop":
                        stop = True
                    elif c[0] == "export":
                        paths = sess.write(c[1], c[2], pdf=True)
                        put({"kind": "export", "paths": {k: str(v) for k, v in paths.items()}})
            except queue.Empty:
                pass
            if stop:
                break
            if done or (paused and not step):
                time.sleep(0.02)
                t_next = time.perf_counter()
                continue
            sess.pat.debug = debug
            r = sess.step()
            if r is None:
                done = True
                extra = {}
                if video:
                    from pathlib import Path

                    out = Path("results") / "gui" / "last_video"
                    p = sess.write(out, Path(video).stem or "video", pdf=False)
                    extra["centroids"] = str(p["centroids"])
                put({"kind": "finished", "metrics": _metrics(sess, cfg) or {},
                           "n_rows": len(sess.logger.rows), **extra})
                continue
            now = time.perf_counter()
            if now - last_metrics > 1.0 or step:
                metrics = _metrics(sess, cfg)
                last_metrics = now
            if now - last_emit >= 1.0 / 30.0 or step or paused:
                try:
                    out_q.put_nowait(_packet(sess, r, metrics, debug))
                    last_emit = now
                except queue.Full:
                    pass
            step = False
            t_next += period / max(speed, 1e-3)
            delay = t_next - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:  # behind schedule: catch up (bounded) so the mean rate stays at camera rate
                t_next = max(t_next, time.perf_counter() - 0.25)
    except Exception:  # pragma: no cover - surfaced in the GUI
        try:
            out_q.put({"kind": "error", "text": traceback.format_exc()}, timeout=2)
        except Exception:
            pass


class LoopWorker(QObject):
    """QThread-side relay for :func:`loop_process` (commands out, packets in as signals)."""

    packet = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    exported = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, cfg: Config, video: str | None = None, truth: str | None = None,
                 speed: float = 1.0, debug: bool = False):
        super().__init__()
        import multiprocessing as mp

        self.ctx = mp.get_context("spawn")
        self.cmd_q = self.ctx.Queue()
        self.out_q = self.ctx.Queue(maxsize=3)
        self.proc = self.ctx.Process(target=loop_process, daemon=True,
                                     args=(copy.deepcopy(cfg), video, truth, speed, debug,
                                           self.cmd_q, self.out_q))
        self._paused = False
        self.stop_flag = False
        self.has_session = False
        self.final: dict | None = None

    # command properties (same interface as a thread-local worker) -----------------
    @property
    def paused(self) -> bool:
        """Pause state."""
        return self._paused

    @paused.setter
    def paused(self, v: bool) -> None:
        self._paused = v
        self.cmd_q.put(("pause", v))

    @property
    def step_once(self) -> bool:
        """Write-only: request a single step."""
        return False

    @step_once.setter
    def step_once(self, v: bool) -> None:
        if v:
            self.cmd_q.put(("step",))

    def set_speed(self, v: float) -> None:
        """Change pacing."""
        self.cmd_q.put(("speed", v))

    def set_debug(self, v: bool) -> None:
        """Enable debug images."""
        self.cmd_q.put(("debug", v))

    def export(self, out_dir: str, name: str) -> None:
        """Ask the loop process to write CSV/JSON/PDF (reply via ``exported``)."""
        self.cmd_q.put(("export", out_dir, name))

    def run(self) -> None:
        """Thread body: start the process and relay its messages."""
        import queue

        self.proc.start()
        while not self.stop_flag:
            try:
                m = self.out_q.get(timeout=0.1)
            except queue.Empty:
                if not self.proc.is_alive():
                    break
                continue
            k = m["kind"]
            if k in ("info", "frame"):
                self.has_session = True
                self.packet.emit(m)
            elif k == "export":
                self.exported.emit(m["paths"])
            elif k == "finished":
                self.final = m
                self.finished.emit(m)
            elif k == "error":
                self.error.emit(m["text"])
                break
        self.cmd_q.put(("stop",))
        self.proc.join(3)
        if self.proc.is_alive():
            self.proc.terminate()


class LoopThread:
    """Owns a QThread + LoopWorker pair."""

    def __init__(self, worker: LoopWorker):
        self.worker = worker
        self.thread = QThread()
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)

    def start(self) -> None:
        """Start the thread (which starts the loop process)."""
        self.thread.start()

    def stop(self) -> None:
        """Stop the loop process and the thread."""
        self.worker.stop_flag = True
        self.thread.quit()
        self.thread.wait(6000)


class BenchWorker(QObject):
    """Runs a benchmark selection off the UI thread."""

    progress = pyqtSignal(int, int)
    done = pyqtSignal(list, str)
    error = pyqtSignal(str)

    def __init__(self, scenarios: list[str], seeds: int, duration: float, acq: str, start: str,
                 out_dir: str, workers: int):
        super().__init__()
        self.args = (scenarios, seeds, duration, acq, start, out_dir, workers)

    def run(self) -> None:
        """Thread body."""
        try:
            from pathlib import Path

            from ..bench.run_bench import aggregate, markdown_table, run_jobs, write_csv
            from ..metrics.report import write_bench_report

            scen, seeds, dur, acq, start, out, workers = self.args
            acqs = ["spiral", "wide_fov"] if acq == "both" else [acq]
            starts = ["random", "in_fov"] if start == "both" else [start]
            jobs = [(sc, sd, a, st, "full", dur, Path(out) / "runs", None)
                    for sc in scen for a in acqs for st in starts for sd in range(seeds)]
            rows = []
            for chunk in range(0, len(jobs), max(workers, 1)):
                rows += run_jobs(jobs[chunk:chunk + max(workers, 1)], workers, "gui-bench")
                self.progress.emit(min(len(rows), len(jobs)), len(jobs))
            agg = aggregate(rows)
            Path(out).mkdir(parents=True, exist_ok=True)
            write_csv(Path(out) / "benchmark_runs.csv", rows)
            write_csv(Path(out) / "benchmark_summary.csv", agg)
            (Path(out) / "benchmark_summary.md").write_text(markdown_table(agg), encoding="utf-8")
            pdf = Path(out) / "benchmark_report.pdf"
            write_bench_report(pdf, agg, rows, {"seeds": seeds, "duration_s": dur,
                                                "perception": "config default"})
            self.done.emit(agg, str(pdf))
        except Exception:  # pragma: no cover
            self.error.emit(traceback.format_exc())
