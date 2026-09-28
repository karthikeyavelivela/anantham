"""Scrolling 30 s live plots with PS threshold lines and a state timeline strip."""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from ..theme import CYAN, NAVY, RED, STATE_RGB


def _plot(title: str, ylabel: str) -> pg.PlotWidget:
    pw = pg.PlotWidget(background="w", title=f"<span style='color:{NAVY}'>{title}</span>")
    pw.showGrid(x=True, y=True, alpha=0.2)
    pw.setLabel("left", ylabel)
    pw.setMenuEnabled(False)
    pw.setMouseEnabled(x=False, y=False)
    return pw


def _hline(pw, y, label=""):
    ln = pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(RED, width=1, style=Qt.PenStyle.DashLine),
                         label=label, labelOpts={"color": RED, "position": 0.05})
    pw.addItem(ln)
    return ln


class LivePlots(QWidget):
    """Centroid error, processing FPS, pan/tilt rates, state timeline."""

    def __init__(self, parent=None, window_s: float = 30.0):
        super().__init__(parent)
        self.window_s = window_s
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.p_err = _plot("Centroiding error", "px")
        self.p_err.setLogMode(y=False)
        self.p_err.setYRange(0, 25)
        self.p_err.enableAutoRange(axis="y", enable=False)
        _hline(self.p_err, 10, "PS 10 px")
        self.c_err = self.p_err.plot(pen=None, symbol="o", symbolSize=3, symbolBrush=CYAN,
                                     symbolPen=None)
        self.c_trk = self.p_err.plot(pen=pg.mkPen(NAVY, width=1))
        self.p_fps = _plot("Processing FPS", "FPS")
        _hline(self.p_fps, 20, "PS 20 FPS")
        self.c_fps = self.p_fps.plot(pen=pg.mkPen(CYAN, width=1.2))
        self.p_rate = _plot("Pan / tilt rate", "°/s")
        self.lim = [_hline(self.p_rate, 5), _hline(self.p_rate, -5)]
        self.c_pan = self.p_rate.plot(pen=pg.mkPen(CYAN, width=1.2), name="pan")
        self.c_tilt = self.p_rate.plot(pen=pg.mkPen(NAVY, width=1.2), name="tilt")
        self.p_state = _plot("State timeline", "")
        self.p_state.hideAxis("left")
        self.strip = pg.ImageItem(axisOrder="row-major")
        self.p_state.addItem(self.strip)
        for w in (self.p_err, self.p_fps, self.p_rate, self.p_state):
            lay.addWidget(w)
        self.reset()

    def set_limits(self, pan: float, tilt: float) -> None:
        """Slew limit lines."""
        m = max(pan, tilt)
        self.lim[0].setPos(m)
        self.lim[1].setPos(-m)

    def reset(self) -> None:
        """Clear all series."""
        n = 4000
        self.t, self.err, self.trk = deque(maxlen=n), deque(maxlen=n), deque(maxlen=n)
        self.fps, self.pan, self.tilt, self.states = (deque(maxlen=n), deque(maxlen=n),
                                                      deque(maxlen=n), deque(maxlen=n))

    def update_packet(self, p: dict, redraw: bool = True) -> None:
        """Append one packet; redraw only when ``redraw`` (throttled by the caller)."""
        self.t.append(p["t"])
        self.err.append(p["centroid_err"])
        self.trk.append(p["track_err"] if p["state"] == "LOCKED" else np.nan)
        self.fps.append(1000.0 / max(p["proc_ms"], 1e-3))
        self.pan.append(p["rate"])
        self.tilt.append(p["rate_t"])
        self.states.append(p["state"])
        if not redraw:
            return
        t = np.fromiter(self.t, float)
        t0 = t[-1] - self.window_s
        sel = t >= t0
        ts = t[sel]
        self.c_err.setData(ts, np.fromiter(self.err, float)[sel], connect="finite")
        self.c_trk.setData(ts, np.fromiter(self.trk, float)[sel], connect="finite")
        self.c_fps.setData(ts, np.fromiter(self.fps, float)[sel])
        self.c_pan.setData(ts, np.fromiter(self.pan, float)[sel])
        self.c_tilt.setData(ts, np.fromiter(self.tilt, float)[sel])
        for pw in (self.p_err, self.p_fps, self.p_rate, self.p_state):
            pw.setXRange(max(t0, 0), max(t[-1], self.window_s) if t0 < 0 else t[-1], padding=0)
        st = [s for s, m in zip(self.states, sel) if m]
        rgb = np.array([STATE_RGB.get(s, (148, 163, 184)) for s in st], np.uint8)[None]
        self.strip.setImage(rgb, autoLevels=False)
        if len(ts) > 1:
            self.strip.setRect(ts[0], 0, ts[-1] - ts[0], 1)
