"""ANANTHAM — FSOC Coarse Alignment Console (PyQt6 + pyqtgraph)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import list_presets, load_preset
from .theme import STYLESHEET
from .widgets.bench_tab import BenchTab
from .widgets.camera_view import CameraView
from .widgets.config_panel import ConfigPanel
from .widgets.debug_view import DebugView
from .widgets.minimap import Minimap
from .widgets.plots import LivePlots
from .widgets.telemetry import TelemetryPanel
from .widgets.video_tab import VideoTab
from .worker import LoopThread, LoopWorker

SPEEDS = ["0.25×", "0.5×", "1×", "2×", "4×"]


class MainWindow(QMainWindow):
    """Main console window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANANTHAM — FSOC Coarse Alignment Console")
        self.loop: LoopThread | None = None
        self.video_mode = False
        self.urad = 109.08
        self._build_toolbar()
        self._build_central()
        self._build_dock()
        self.statusBar().showMessage(f"ANANTHAM {__version__} — ready")
        self._load_scenario("default")

    # ------------------------------------------------------------------ layout
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.b_sim, self.b_mp4 = QPushButton("SIMULATION"), QPushButton("EVALUATOR MP4")
        grp = QButtonGroup(self)
        for b in (self.b_sim, self.b_mp4):
            b.setCheckable(True)
            grp.addButton(b)
            tb.addWidget(b)
        self.b_sim.setChecked(True)
        self.b_sim.clicked.connect(lambda: self._set_mode(False))
        self.b_mp4.clicked.connect(lambda: self._set_mode(True))
        tb.addSeparator()
        self.b_start = QPushButton("▶ Start")
        self.b_start.setObjectName("primary")
        self.b_pause, self.b_step, self.b_reset = QPushButton("⏸ Pause"), QPushButton("⏭ Step"), \
            QPushButton("⟲ Reset")
        for b, fn in ((self.b_start, self.start), (self.b_pause, self.pause),
                      (self.b_step, self.step), (self.b_reset, self.reset)):
            b.clicked.connect(fn)
            tb.addWidget(b)
        tb.addSeparator()
        tb.addWidget(QLabel(" Scenario "))
        self.scenario = QComboBox()
        self.scenario.addItems(list_presets())
        self.scenario.setCurrentText("default")
        self.scenario.currentTextChanged.connect(self._load_scenario)
        tb.addWidget(self.scenario)
        tb.addWidget(QLabel(" Seed "))
        self.seed = QSpinBox()
        self.seed.setRange(0, 10 ** 6)
        self.seed.setMaximumWidth(80)
        self.scenario.setMaximumWidth(170)
        tb.addWidget(self.seed)
        tb.addWidget(QLabel(" Speed "))
        self.speed = QComboBox()
        self.speed.addItems(SPEEDS)
        self.speed.setCurrentText("1×")
        self.speed.setMaximumWidth(70)
        self.speed.currentTextChanged.connect(self._speed_changed)
        tb.addWidget(self.speed)
        tb.addSeparator()
        self.b_export = QPushButton("Export Report")
        for b in (self.b_sim, self.b_mp4, self.b_start, self.b_pause, self.b_step, self.b_reset):
            b.setStyleSheet("padding: 4px 6px;")
        self.b_export.clicked.connect(self.export_report)
        tb.addWidget(self.b_export)
        self.b_blind = QPushButton("Blind: OFF")
        self.b_blind.setCheckable(True)
        self.b_blind.toggled.connect(self._blind_changed)
        tb.addWidget(self.b_blind)

    def _build_central(self) -> None:
        self.tabs = QTabWidget()
        track = QWidget()
        v = QVBoxLayout(track)
        v.setContentsMargins(4, 4, 4, 4)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        hsplit = QSplitter(Qt.Orientation.Horizontal)
        left = QSplitter(Qt.Orientation.Vertical)
        self.camera = CameraView()
        self.minimap = Minimap()
        self.minimap.clicked.connect(self._minimap_click)
        left.addWidget(self.camera)
        left.addWidget(self.minimap)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 1)
        self.telemetry = TelemetryPanel()
        hsplit.addWidget(left)
        hsplit.addWidget(self.telemetry)
        hsplit.setStretchFactor(0, 3)
        hsplit.setStretchFactor(1, 1)
        self.plots = LivePlots()
        vsplit.addWidget(hsplit)
        vsplit.addWidget(self.plots)
        vsplit.setStretchFactor(0, 4)
        vsplit.setStretchFactor(1, 1)
        v.addWidget(vsplit)
        vsplit.setSizes([720, 260])
        left.setSizes([560, 170])
        hsplit.setSizes([1100, 330])
        self.tabs.addTab(track, "Tracking")
        self.debug = DebugView()
        self.tabs.addTab(self.debug, "Perception Debug")
        self.bench = BenchTab()
        self.tabs.addTab(self.bench, "Benchmark")
        self.video = VideoTab()
        self.video.run_requested.connect(self._run_video)
        self.tabs.addTab(self.video, "Evaluator MP4")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

    def _build_dock(self) -> None:
        self.config = ConfigPanel()
        dock = QDockWidget("CONFIGURATION", self)
        dock.setWidget(self.config)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setMinimumWidth(290)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    # ------------------------------------------------------------------ actions
    def _load_scenario(self, name: str) -> None:
        try:
            cfg = load_preset(name)
        except Exception as exc:  # pragma: no cover
            self.statusBar().showMessage(str(exc))
            return
        cfg.run.name = name
        self.config.set_config(cfg)

    def _set_mode(self, video: bool) -> None:
        self.video_mode = video
        self.b_blind.setChecked(True if video else self.b_blind.isChecked())
        self.b_blind.setEnabled(not video)
        if video:
            self.tabs.setCurrentWidget(self.video)

    def _blind_changed(self, on: bool) -> None:
        self.b_blind.setText(f"Blind: {'ON' if on else 'OFF'}")
        self.camera.set_blind(on)
        self.minimap.set_blind(on)

    def _speed_changed(self, s: str) -> None:
        if self.loop:
            self.loop.worker.set_speed(float(s.rstrip("×")))

    def _tab_changed(self, i: int) -> None:
        if self.loop:
            self.loop.worker.set_debug(self.tabs.widget(i) is self.debug)

    def _minimap_click(self, x: float, y: float) -> None:
        if not self.video_mode:
            self.config.set_start(x, y)
            self.statusBar().showMessage(f"target start set to ({x:.0f}, {y:.0f}) screen px")

    def _cfg(self):
        issues = self.config.issues_list()
        if any(getattr(i, "severity", "error") == "error" for i in issues):
            QMessageBox.warning(self, "Configuration", "Fix the configuration errors first.")
            return None
        ps = [i for i in issues if getattr(i, "severity", "") == "ps"]
        if ps and QMessageBox.question(
                self, "Outside PS range", "\n".join(str(i) for i in ps[:8]) + "\n\nRun anyway?"
        ) != QMessageBox.StandardButton.Yes:
            return None
        cfg = self.config.get_config()
        cfg.run.seed = self.seed.value()
        cfg.run.name = f"{self.scenario.currentText()}_s{cfg.run.seed}"
        return cfg

    def start(self, video: str | None = None, truth: str | None = None) -> None:
        """Start (or resume) the loop."""
        if self.loop and self.loop.thread.isRunning() and self.loop.worker.final is None:
            self.loop.worker.paused = False
            return
        cfg = self._cfg()
        if cfg is None:
            return
        if self.video_mode and not video:
            video, truth = self.video.path.text() or None, self.video.truth.text() or None
            if not video:
                self.tabs.setCurrentWidget(self.video)
                self.statusBar().showMessage("select an MP4 file first")
                return
        self.reset(keep_status=True)
        w = LoopWorker(cfg, video, truth or None, float(self.speed.currentText().rstrip("×")),
                       self.tabs.currentWidget() is self.debug)
        w.packet.connect(self._on_packet)
        w.finished.connect(self._on_finished)
        w.exported.connect(self._on_exported)
        w.error.connect(lambda e: QMessageBox.critical(self, "Run failed", e))
        self.loop = LoopThread(w)
        self.plots.set_limits(cfg.camera.max_pan_rate_deg_s, cfg.camera.max_tilt_rate_deg_s)
        self.minimap.set_screen(cfg.camera.screen_w_px, cfg.camera.screen_h_px)
        self.minimap.fov_px = (cfg.camera.res_w, cfg.camera.res_h)
        self.minimap.setVisible(video is None)
        self.loop.start()
        self.statusBar().showMessage(f"running {cfg.run.name} ({'MP4' if video else 'simulation'})")

    def pause(self) -> None:
        """Pause the loop."""
        if self.loop:
            self.loop.worker.paused = True

    def step(self) -> None:
        """Advance exactly one frame."""
        if not self.loop or not self.loop.thread.isRunning():
            self.start()
            if self.loop:
                self.loop.worker.paused = True
        if self.loop:
            self.loop.worker.paused = True
            self.loop.worker.step_once = True

    def reset(self, keep_status: bool = False) -> None:
        """Stop the loop and clear displays."""
        if self.loop:
            self.loop.stop()
        self.loop = None
        self.plots.reset()
        self.minimap.reset()
        if not keep_status:
            self.statusBar().showMessage("reset")

    def _run_video(self, path: str, truth: str) -> None:
        self.b_mp4.setChecked(True)
        self._set_mode(True)
        self.start(path, truth)

    def export_report(self) -> None:
        """Write CSV / JSON / PDF for the current (or finished) run."""
        if not self.loop or not self.loop.worker.has_session:
            self.statusBar().showMessage("nothing to export yet")
            return
        self.pause()
        name = self.scenario.currentText() + f"_s{self.seed.value()}" if not self.video_mode \
            else Path(self.video.path.text()).stem
        out = Path("results") / "gui" / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"
        self.loop.worker.export(str(out), name)
        self.statusBar().showMessage("writing report…")

    def _on_exported(self, paths: dict) -> None:
        self.video.last_csv = paths.get("centroids")
        QMessageBox.information(self, "Report exported", "\n".join(f"{k}: {v}" for k, v in paths.items()))

    # ------------------------------------------------------------------ updates
    def _on_packet(self, p: dict) -> None:
        if p["kind"] == "info":
            self.telemetry.geometry.setText(p["geometry"])
            self.minimap.set_path(p.get("search_path"))
            self.video.set_video_info(p.get("video"))
            return
        # camera at the display rate; the rest throttled so painting never starves the loop
        now = time.perf_counter()
        last = getattr(self, "_last_draw", {})
        self._last_draw = last

        def due(key: str, hz: float) -> bool:
            if now - last.get(key, 0.0) >= 1.0 / hz or p.get("final"):
                last[key] = now
                return True
            return False

        self.camera.update_packet(p)
        if not self.video_mode:
            self.minimap.update_packet(p, redraw=due("mini", 10))
        if due("tele", 10):
            self.telemetry.update_packet(p, self.urad)
        self.plots.update_packet(p, redraw=due("plots", 5))
        if self.tabs.currentWidget() is self.debug:
            self.debug.update_packet(p)

    def _on_finished(self, fin: dict) -> None:
        metrics = fin.get("metrics") or {}
        msg = "run complete"
        if metrics:
            msg += (f" — acquisition {metrics.get('acquisition_time_s', float('nan')):.2f} s, "
                    f"target loss {100 * (metrics.get('target_loss') or 0):.2f} %, "
                    f"{metrics.get('processing_fps', 0):.0f} processing FPS")
        self.statusBar().showMessage(msg + " — use Export Report to save logs + PDF")
        if fin.get("centroids"):
            self.video.last_csv = fin["centroids"]
            self.video.result.setText(f"Per-frame centroids: {fin['centroids']}")

    def closeEvent(self, ev) -> None:  # noqa: N802
        """Stop the worker thread on close."""
        self.reset()
        super().closeEvent(ev)


def main(argv: list[str] | None = None) -> None:
    """Launch the GUI. Dev options: --screenshot PATH --seconds N --preset NAME --size WxH."""
    import argparse

    ap = argparse.ArgumentParser(prog="anantham gui")
    ap.add_argument("--screenshot")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--preset", default="default")
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--tab", default="Tracking")
    args, _ = ap.parse_known_args(argv if argv is not None else [])
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyleSheet(STYLESHEET)
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, foreground="#1B2A4A")
    win = MainWindow()
    w, h = (int(x) for x in args.size.split("x"))
    win.resize(w, h)
    win.show()
    if args.screenshot:
        win.scenario.setCurrentText(args.preset)
        win.config.widgets["perception.mode"][0].setCurrentText(
            win.config.widgets["perception.mode"][0].currentText())
        QTimer.singleShot(300, win.start)
        for i in range(win.tabs.count()):
            if win.tabs.tabText(i) == args.tab:
                QTimer.singleShot(200, lambda i=i: win.tabs.setCurrentIndex(i))

        def shot():
            win.grab().save(args.screenshot)
            win.reset()
            app.quit()

        QTimer.singleShot(int(args.seconds * 1000), shot)
    app.exec()


if __name__ == "__main__":
    main(sys.argv[1:])
