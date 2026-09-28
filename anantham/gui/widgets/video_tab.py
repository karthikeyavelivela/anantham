"""Evaluator MP4 tab: pick a video (+ optional truth CSV), inspect it, run, export CSV."""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class VideoTab(QWidget):
    """MP4 selection and per-frame centroid CSV export."""

    run_requested = pyqtSignal(str, str)
    export_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.path = QLineEdit()
        self.truth = QLineEdit()
        b1, b2 = QPushButton("Browse…"), QPushButton("Browse…")
        b1.clicked.connect(self._pick_video)
        b2.clicked.connect(self._pick_truth)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        r1.addWidget(self.path, 1)
        r1.addWidget(b1)
        r2.addWidget(self.truth, 1)
        r2.addWidget(b2)
        form.addRow("MP4 file", r1)
        form.addRow("Truth CSV (optional)", r2)
        self.info = QLabel("No video loaded.")
        self.info.setWordWrap(True)
        form.addRow("Detected", self.info)
        lay.addLayout(form)
        note = QLabel("Evaluator mode bypasses the PTZ camera: the same perception and tracking "
                      "stack runs on the video; the boresight is virtual (slew-limited inside the "
                      "image). Blind mode is always ON. Truth CSV format: frame,time_s,x_px,y_px"
                      "[,visible] with pixel centres at i+0.5.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#475569;")
        lay.addWidget(note)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run on video")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(lambda: self.run_requested.emit(self.path.text(), self.truth.text()))
        self.exp_btn = QPushButton("Export per-frame centroid CSV…")
        self.exp_btn.clicked.connect(self._export)
        row.addWidget(self.run_btn)
        row.addWidget(self.exp_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        lay.addStretch(1)
        self.last_csv: str | None = None

    def _pick_video(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select video", "", "Video (*.mp4 *.avi *.mov *.mkv)")
        if p:
            self.path.setText(p)
            cap = cv2.VideoCapture(p)
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps, n = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            self.info.setText(f"{w}×{h} @ {fps:.2f} fps, {n} frames (spot scale estimated at run)")
            cand = Path(p).with_name(Path(p).stem + "_truth.csv")
            if cand.exists() and not self.truth.text():
                self.truth.setText(str(cand))

    def _pick_truth(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select truth CSV", "", "CSV (*.csv)")
        if p:
            self.truth.setText(p)

    def set_video_info(self, v: dict | None) -> None:
        """Show detected resolution / fps / spot scale."""
        if v:
            self.info.setText(f"{v['width']}×{v['height']} @ {v['fps']:.2f} fps — spot scale "
                              f"{v['spot_size_px']:.2f} px ({v['spot_size_source']})")

    def _export(self) -> None:
        if not self.last_csv:
            self.result.setText("Run a video first.")
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save centroid CSV", "centroids.csv", "CSV (*.csv)")
        if p:
            shutil.copyfile(self.last_csv, p)
            self.result.setText(f"Saved {p}")
