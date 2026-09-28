"""Camera view with togglable overlays (pyqtgraph)."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..theme import AMBER, CYAN, GREEN, GREY, NAVY

OVERLAYS = [("bore", "Boresight"), ("meas", "Centroid"), ("pred", "Kalman ±1σ"),
            ("track", "Predicted track"), ("rej", "Rejected"), ("truth", "Truth (sim)")]


class CameraView(QWidget):
    """640×480 (or video-sized) image with PAT overlays, crisp nearest-neighbour scaling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blind = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel("CAMERA VIEW")
        self.title.setStyleSheet(f"font-weight:bold; color:{NAVY};")
        head.addWidget(self.title)
        head.addStretch(1)
        self.toggles = {}
        for key, label in OVERLAYS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(self._apply_visibility)
            self.toggles[key] = cb
            head.addWidget(cb)
        lay.addLayout(head)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("w")
        self.vb = self.glw.addViewBox(lockAspect=True, invertY=True, enableMouse=False)
        self.vb.setMenuEnabled(False)
        self.img = pg.ImageItem(axisOrder="row-major")
        self.vb.addItem(self.img)
        pen = lambda c, w=1.5, s=None: pg.mkPen(c, width=w, style=s)  # noqa: E731
        self.bore = pg.PlotDataItem(pen=pen(NAVY, 1.2))
        self.meas = pg.PlotDataItem(pen=pen(CYAN, 2))
        self.pred = pg.PlotDataItem(pen=pen(AMBER, 1.6))
        self.pred_pt = pg.ScatterPlotItem(size=6, brush=pg.mkBrush(AMBER), pen=None)
        from PyQt6.QtCore import Qt

        self.track = pg.PlotDataItem(pen=pen(AMBER, 1.2, Qt.PenStyle.DotLine))
        self.rej = pg.ScatterPlotItem(size=9, symbol="x", pen=pg.mkPen(GREY, width=1.5), brush=None)
        self.truth = pg.ScatterPlotItem(size=9, brush=pg.mkBrush(GREEN), pen=pg.mkPen("w"))
        self.others = pg.ScatterPlotItem(size=7, brush=pg.mkBrush(GREY), pen=None)
        for it in (self.bore, self.meas, self.pred, self.pred_pt, self.track, self.rej, self.others,
                   self.truth):
            self.vb.addItem(it)
        self.text = pg.TextItem("", color=NAVY, anchor=(0, 0))
        self.vb.addItem(self.text)
        lay.addWidget(self.glw, 1)
        self.shape = None

    def set_blind(self, blind: bool) -> None:
        """Blind mode hides every truth overlay."""
        self.blind = blind
        self.toggles["truth"].setEnabled(not blind)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        t = self.toggles
        self.bore.setVisible(t["bore"].isChecked())
        self.meas.setVisible(t["meas"].isChecked())
        self.pred.setVisible(t["pred"].isChecked())
        self.pred_pt.setVisible(t["pred"].isChecked())
        self.track.setVisible(t["track"].isChecked())
        self.rej.setVisible(t["rej"].isChecked())
        show_truth = t["truth"].isChecked() and not self.blind
        self.truth.setVisible(show_truth)
        self.others.setVisible(show_truth)

    def update_packet(self, p: dict) -> None:
        """Draw one frame packet."""
        img = p["image"]
        if img.ndim == 3:
            img = img[..., ::-1]
        self.img.setImage(img, autoLevels=False, levels=(0, 255))
        h, w = img.shape[:2]
        if self.shape != (h, w):
            self.shape = (h, w)
            self.vb.setRange(xRange=(0, w), yRange=(0, h), padding=0.01)
        cx, cy = w / 2, h / 2
        L = 0.04 * w
        self.bore.setData([cx - L, cx + L, np.nan, cx, cx], [cy, cy, np.nan, cy - L, cy + L],
                          connect="finite")
        m = p["meas"]
        if m is not None:
            s = max(8.0, 0.02 * w)
            self.meas.setData([m[0] - s, m[0] + s, m[0] + s, m[0] - s, m[0] - s],
                              [m[1] - s, m[1] - s, m[1] + s, m[1] + s, m[1] - s])
        else:
            self.meas.setData([], [])
        pr = p["pred"]
        if pr is not None and p["ellipse"] is not None:
            a, b, ang = p["ellipse"]
            a, b = max(a, 1.0), max(b, 1.0)
            t = np.linspace(0, 2 * math.pi, 40)
            ex = pr[0] + a * np.cos(t) * math.cos(ang) - b * np.sin(t) * math.sin(ang)
            ey = pr[1] + a * np.cos(t) * math.sin(ang) + b * np.sin(t) * math.cos(ang)
            self.pred.setData(ex, ey)
            self.pred_pt.setData([pr[0]], [pr[1]])
            v = p["vel"] or (0.0, 0.0)
            k = np.arange(0, 16)
            self.track.setData(pr[0] + v[0] * k, pr[1] + v[1] * k)
        else:
            self.pred.setData([], [])
            self.pred_pt.setData([], [])
            self.track.setData([], [])
        rej = [(c[0], c[1]) for c in p["cands"] if not c[2]]
        self.rej.setData([r[0] for r in rej], [r[1] for r in rej])
        tr = p["truth"]
        self.truth.setData([] if tr is None else [tr[0]], [] if tr is None else [tr[1]])
        od = p.get("distractors") or []
        self.others.setData([o[0] for o in od], [o[1] for o in od])
        self.text.setText(f"frame {p['k']}  t={p['t']:.2f}s  {p['mode']}")
