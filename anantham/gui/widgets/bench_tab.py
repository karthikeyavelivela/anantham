"""Benchmark tab: pick scenarios and seeds, run in the background, colour PASS/FAIL."""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...bench.scenarios import SCENARIOS
from ..worker import BenchWorker

COLS = [("scenario", None), ("acq", None), ("start", None), ("seeds", None),
        ("acq_time_s_worst", 2.0), ("cent_rmse_px_worst", 10.0), ("trk_rmse_px_worst", 10.0),
        ("trk_ss_rmse_px_worst", 10.0), ("target_loss_worst", 0.05), ("reacq_max_s_worst", 1.0),
        ("proc_fps_worst", -20.0), ("pass_rate", None)]
LABELS = ["scenario", "acq.", "start", "seeds", "acq. time s\n(worst)", "centroid RMSE\npx (worst)",
          "track RMSE all\npx (worst)", "track RMSE steady\npx (worst)", "target loss\n(worst)",
          "re-acq s\n(worst)", "proc FPS\n(min)", "all-PS\npass rate"]


class BenchTab(QWidget):
    """Background benchmark runner with a results table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("Scenarios"))
        self.list = QListWidget()
        for n in SCENARIOS:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if n in ("circular", "salt_pepper", "fog")
                             else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.seeds = QSpinBox()
        self.seeds.setRange(1, 50)
        self.seeds.setValue(2)
        self.dur = QDoubleSpinBox()
        self.dur.setRange(2, 300)
        self.dur.setValue(15)
        self.acq = QComboBox()
        self.acq.addItems(["spiral", "wide_fov", "both"])
        self.start = QComboBox()
        self.start.addItems(["in_fov", "random", "both"])
        for lab, w in (("seeds", self.seeds), ("s", self.dur), ("acq", self.acq), ("start", self.start)):
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        left.addLayout(row)
        self.run_btn = QPushButton("Run benchmark")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        left.addWidget(self.run_btn)
        self.bar = QProgressBar()
        left.addWidget(self.bar)
        self.open_btn = QPushButton("Open report")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open)
        left.addWidget(self.open_btn)
        lay.addLayout(left, 1)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(LABELS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 3)
        self.report = None
        self.out_dir = str(Path("results") / "gui_bench")

    def run(self) -> None:
        """Start the benchmark in a QThread."""
        scen = [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if not scen:
            return
        self.run_btn.setEnabled(False)
        self.worker = BenchWorker(scen, self.seeds.value(), self.dur.value(), self.acq.currentText(),
                                  self.start.currentText(), self.out_dir, 2)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda i, n: (self.bar.setMaximum(n), self.bar.setValue(i)))
        self.worker.done.connect(self._done)
        self.worker.error.connect(lambda e: (self.run_btn.setEnabled(True), print(e)))
        self.worker.done.connect(self.thread.quit)
        self.thread.start()

    def _done(self, agg: list, pdf: str) -> None:
        self.run_btn.setEnabled(True)
        self.report = pdf
        self.open_btn.setEnabled(True)
        self.table.setRowCount(len(agg))
        for r, a in enumerate(agg):
            for c, (key, thr) in enumerate(COLS):
                v = a.get(key)
                txt = f"{v:.3g}" if isinstance(v, float) and not math.isnan(v) else str(v)
                it = QTableWidgetItem(txt)
                if thr is not None and isinstance(v, float) and not math.isnan(v):
                    ok = v >= -thr if thr < 0 else (v < thr if key == "target_loss_worst" else v <= thr)
                    it.setBackground(QColor("#DCFCE7" if ok else "#FEE2E2"))
                if key == "pass_rate":
                    it.setBackground(QColor("#DCFCE7" if v == 1 else "#FEE2E2"))
                self.table.setItem(r, c, it)

    def _open(self) -> None:
        if self.report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.report).resolve())))
