"""Scene minimap: the whole screen with FOV rectangle, search path and trails."""

from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import AMBER, CYAN, GREEN, GREY, NAVY


class Minimap(QWidget):
    """Screen-scale overview. Click to set a user start position (simulation)."""

    clicked = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("SCENE MINIMAP (click = set target start)")
        self.label.setStyleSheet(f"font-weight:bold; color:{NAVY};")
        lay.addWidget(self.label)
        self.pw = pg.PlotWidget(background="w")
        self.pw.setAspectLocked(True)
        self.pw.invertY(True)
        self.pw.hideButtons()
        self.pw.setMenuEnabled(False)
        self.pw.getPlotItem().hideAxis("left")
        self.pw.getPlotItem().hideAxis("bottom")
        lay.addWidget(self.pw, 1)
        self.screen = pg.PlotDataItem(pen=pg.mkPen(NAVY, width=1.5))
        self.path = pg.PlotDataItem(pen=pg.mkPen(GREY, width=1, style=Qt.PenStyle.DashLine))
        self.fov = pg.PlotDataItem(pen=pg.mkPen(CYAN, width=2))
        self.trail_true = pg.PlotDataItem(pen=pg.mkPen(GREEN, width=1.5))
        self.trail_est = pg.PlotDataItem(pen=pg.mkPen(AMBER, width=1.5))
        self.start_pt = pg.ScatterPlotItem(size=10, symbol="+", pen=pg.mkPen(NAVY, width=2))
        for it in (self.screen, self.path, self.fov, self.trail_true, self.trail_est, self.start_pt):
            self.pw.addItem(it)
        self.true_hist: deque = deque(maxlen=600)
        self.est_hist: deque = deque(maxlen=600)
        self.blind = False
        self.fov_px = (640, 480)
        self.pw.scene().sigMouseClicked.connect(self._on_click)
        self.set_screen(2000, 2000)

    def set_screen(self, w: float, h: float) -> None:
        """Draw the screen outline."""
        self.sw, self.sh = w, h
        self.screen.setData([0, w, w, 0, 0], [0, 0, h, h, 0])
        self.pw.setRange(xRange=(-50, w + 50), yRange=(-50, h + 50), padding=0)

    def set_path(self, pts) -> None:
        """Global search path (pointing px)."""
        if pts:
            self.path.setData([p[0] for p in pts], [p[1] for p in pts])
        else:
            self.path.setData([], [])

    def reset(self) -> None:
        """Clear trails."""
        self.true_hist.clear()
        self.est_hist.clear()
        self.trail_true.setData([], [])
        self.trail_est.setData([], [])

    def set_blind(self, blind: bool) -> None:
        """Hide truth trail in blind mode."""
        self.blind = blind
        self.trail_true.setVisible(not blind)

    def update_packet(self, p: dict, redraw: bool = True) -> None:
        """Update FOV rectangle and trails from a frame packet."""
        bu, bv = p["bore_px"]
        w, h = self.fov_px
        self.fov.setData([bu - w / 2, bu + w / 2, bu + w / 2, bu - w / 2, bu - w / 2],
                         [bv - h / 2, bv - h / 2, bv + h / 2, bv + h / 2, bv - h / 2])
        ts = p.get("truth_screen")
        if ts and ts[0] is not None:
            self.true_hist.append(ts)
        if p.get("pred_ptg") and p["state"] in ("LOCKED", "COAST"):
            self.est_hist.append(p["pred_ptg"])
        if redraw:
            self.trail_true.setData([q[0] for q in self.true_hist], [q[1] for q in self.true_hist])
            self.trail_est.setData([q[0] for q in self.est_hist], [q[1] for q in self.est_hist])

    def _on_click(self, ev) -> None:
        pos = self.pw.getPlotItem().vb.mapSceneToView(ev.scenePos())
        x, y = float(pos.x()), float(pos.y())
        if 0 <= x <= self.sw and 0 <= y <= self.sh:
            self.start_pt.setData([x], [y])
            self.clicked.emit(x, y)
