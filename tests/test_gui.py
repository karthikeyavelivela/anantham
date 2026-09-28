"""GUI smoke test (offscreen): the window builds, runs a few frames in a QThread, blind mode."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qt = pytest.importorskip("PyQt6.QtWidgets")


def test_window_runs_frames():
    from PyQt6.QtWidgets import QApplication

    from anantham.gui.app import MainWindow
    from anantham.gui.theme import STYLESHEET

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.resize(1366, 768)
    win.show()
    assert win.windowTitle() == "ANANTHAM — FSOC Coarse Alignment Console"
    win.scenario.setCurrentText("circular")
    win.config.widgets["perception.mode"][0].setCurrentText("classical")
    win.config.widgets["target.start"][0].setCurrentText("in_fov")
    win.config.widgets["run.duration_s"][0].setValue(2.0)
    win.speed.setCurrentText("4×")
    win.start()
    t0 = time.time()
    while time.time() - t0 < 60 and win.loop.worker.final is None:
        app.processEvents()
        time.sleep(0.01)
    fin = win.loop.worker.final
    assert fin is not None and fin["n_rows"] == 60
    assert fin["metrics"]["locked_frames"] > 0
    win.b_blind.setChecked(True)
    assert not win.camera.truth.isVisible()
    # an out-of-range value is flagged
    win.config.widgets["target.size_px"][0].setValue(25.0)
    assert any(i.path == "target.size_px" for i in win.config.issues_list())
    win.close()
