"""Perception debug tab: pipeline stages, CNN heatmap and the candidate table."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

STAGES = [("raw", "Raw"), ("median", "3×3 median"), ("tophat", "Top-hat"), ("mask", "Threshold mask"),
          ("heat", "CNN heatmap (best candidate ROI)")]
COLS = ["x", "y", "score", "size_match", "snr", "cnn", "edge", "accepted", "reason"]


class DebugView(QWidget):
    """Shows the classical pipeline stages and a candidate table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        self.views = {}
        for i, (k, title) in enumerate(STAGES):
            box = QVBoxLayout()
            lab = QLabel(title)
            lab.setStyleSheet("font-weight:bold;")
            glw = pg.GraphicsLayoutWidget()
            glw.setBackground("w")
            vb = glw.addViewBox(lockAspect=True, invertY=True, enableMouse=False)
            img = pg.ImageItem(axisOrder="row-major")
            vb.addItem(img)
            w = QWidget()
            box.addWidget(lab)
            box.addWidget(glw, 1)
            w.setLayout(box)
            grid.addWidget(w, i // 3, i % 3)
            self.views[k] = img
        lay.addLayout(grid, 3)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        lay.addWidget(self.table, 2)
        self.cnn = None

    def update_packet(self, p: dict) -> None:
        """Refresh from a frame packet carrying debug images."""
        dbg = p.get("debug") or {}
        img = p["image"]
        gray = img if img.ndim == 2 else img.mean(axis=2).astype(np.uint8)
        self.views["raw"].setImage(gray, autoLevels=False, levels=(0, 255))
        for k in ("median", "tophat", "mask"):
            if k in dbg:
                self.views[k].setImage(dbg[k], autoLevels=(k == "tophat"))
        acc = [c for c in p["cands"] if c[3].get("cnn") is not None]
        if acc:
            self._heat(gray, acc[0][0], acc[0][1])
        rows = [c[3] for c in p["cands"]]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(COLS):
                it = QTableWidgetItem(str(row.get(key, "")))
                if key == "accepted":
                    good = row.get("accepted") and not str(row.get("reason", "")).startswith(
                        ("size", "edge", "low", "rejected", "cnn"))
                    it.setBackground(QColor("#DCFCE7" if good else "#FEE2E2"))
                self.table.setItem(r, c, it)

    def _heat(self, gray: np.ndarray, x: float, y: float) -> None:
        try:
            if self.cnn is None:
                from ...perception.cnn import CnnVerifier

                self.cnn = CnnVerifier()
            from ...perception.cnn import extract_roi, normalise_roi

            roi, _, _ = extract_roi(gray, x, y, 64)
            _, heat, _ = self.cnn.infer(normalise_roi(roi)[None, None])
            h = 1 / (1 + np.exp(-heat[0]))
            self.views["heat"].setImage(np.kron(h, np.ones((4, 4))), levels=(0, 1))
        except Exception:  # model missing etc. — keep the tab usable
            pass
