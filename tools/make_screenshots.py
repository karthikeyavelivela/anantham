"""Regenerate the README / manual screenshots from the real GUI (offscreen).

    QT_QPA_PLATFORM=offscreen python tools/make_screenshots.py docs/img

Each shot starts a real run (simulation or MP4) in the console, waits, and grabs the
window. Nothing is mocked: every value visible in a screenshot is live output.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


def _pump(app, seconds: float) -> None:
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def _tab(win, name: str) -> None:
    for i in range(win.tabs.count()):
        if win.tabs.tabText(i) == name:
            win.tabs.setCurrentIndex(i)


def _sim(app, win, out: Path, preset: str, seconds: float, tab: str = "Tracking",
         cfg_tab: int = 0, blind: bool = False, **fields) -> None:
    win.reset()
    win.b_sim.click()
    win.scenario.setCurrentText(preset)
    win.config.widgets["run.duration_s"][0].setValue(60.0)
    for k, v in fields.items():
        w = win.config.widgets[k.replace("__", ".")][0]
        if hasattr(w, "setCurrentText") and isinstance(v, str):
            w.setCurrentText(v)
        else:
            w.setValue(v)
    win.config.tabs.setCurrentIndex(cfg_tab)
    win.b_blind.setChecked(blind)
    _tab(win, tab)
    _pump(app, 0.3)
    win.start()
    _pump(app, seconds)
    win.grab().save(str(out))
    print("wrote", out)


def main(out_dir: str) -> None:
    from anantham.config import load_preset
    from anantham.gui.app import MainWindow
    from anantham.gui.theme import STYLESHEET
    from anantham.tools_video import make_test_video

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(STYLESHEET)
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, foreground="#1B2A4A")
    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    _pump(app, 0.5)

    _sim(app, win, out / "gui_tracking.png", "circular", 9.0, target__start="in_fov")
    _sim(app, win, out / "gui_combined.png", "combined", 9.0, cfg_tab=2, target__start="in_fov")
    _sim(app, win, out / "gui_blink.png", "blink", 7.0, cfg_tab=1, target__start="in_fov")
    _sim(app, win, out / "gui_search.png", "circular", 2.5, target__start="random")
    _sim(app, win, out / "gui_debug.png", "rain", 6.0, tab="Perception Debug",
         target__start="in_fov")

    # Evaluator MP4 mode on a synthetic evaluator-style video
    cfg = load_preset("fog")
    cfg.run.duration_s = 20.0
    info = make_test_video(cfg, out.parent / "_shot_video" / "fog_eval.mp4")
    win.reset()
    win.b_mp4.click()
    win.video.path.setText(info["video"])
    win.video.truth.setText(info["truth"])
    _pump(app, 0.3)
    win.start(info["video"], info["truth"])
    _pump(app, 8.0)
    _tab(win, "Tracking")
    _pump(app, 1.0)
    win.grab().save(str(out / "gui_mp4_tracking.png"))
    t0 = time.time()
    while win.loop.worker.final is None and time.time() - t0 < 40:
        _pump(app, 0.5)
    _tab(win, "Evaluator MP4")
    _pump(app, 1.0)
    win.grab().save(str(out / "gui_mp4_tab.png"))
    print("wrote MP4 shots")

    # Benchmark tab: a small real benchmark run from the GUI
    win.reset()
    win.b_sim.click()
    _tab(win, "Benchmark")
    b = win.bench
    for i in range(b.list.count()):
        it = b.list.item(i)
        it.setCheckState(Qt.CheckState.Checked if it.text() in ("circular", "fog", "jitter10",
                                                               "blink") else Qt.CheckState.Unchecked)
    b.seeds.setValue(1)
    b.dur.setValue(6.0)
    b.start.setCurrentText("in_fov")
    b.out_dir = str(out.parent / "_shot_bench")
    b.run()
    t0 = time.time()
    while not b.run_btn.isEnabled() and time.time() - t0 < 300:
        _pump(app, 0.5)
    _pump(app, 0.5)
    win.grab().save(str(out / "gui_benchmark.png"))
    print("wrote benchmark shot")
    win.reset()
    app.quit()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
