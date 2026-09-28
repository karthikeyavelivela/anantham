"""Telemetry cards (right-hand panel)."""

from __future__ import annotations

import math

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from ..theme import GREEN, RED, STATE_COLORS


class Card(QFrame):
    """Title / value / sub-line card."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(0)
        self.t = QLabel(title)
        self.t.setObjectName("cardTitle")
        self.v = QLabel("—")
        self.v.setObjectName("cardValue")
        self.s = QLabel("")
        self.s.setObjectName("cardSub")
        for w in (self.t, self.v, self.s):
            lay.addWidget(w)

    def set(self, value: str, sub: str = "", ok: bool | None = None) -> None:
        """Set value text; ok=True/False colours it green/red."""
        self.v.setText(value)
        self.s.setText(sub)
        color = "" if ok is None else (GREEN if ok else RED)
        self.v.setStyleSheet(f"color:{color};" if color else "")


def _f(v, nd=2, unit=""):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{v:.{nd}f}{unit}"


class TelemetryPanel(QWidget):
    """STATE label and metric cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.state = QLabel("—")
        self.state.setObjectName("stateLabel")
        self.state.setMinimumHeight(52)
        self._state_color("—")
        lay.addWidget(self.state)
        self.geometry = QLabel("")
        self.geometry.setObjectName("cardSub")
        self.geometry.setWordWrap(True)
        lay.addWidget(self.geometry)
        grid = QGridLayout()
        grid.setSpacing(4)
        names = [("cent", "Centroiding error"), ("track", "Tracking error"),
                 ("acq", "Acquisition time"), ("reacq", "Re-acquisitions"),
                 ("ret", "Lock retention"), ("loss", "Target loss"),
                 ("fps", "Processing FPS"), ("ms", "Processing time"),
                 ("pan", "Pan angle / rate"), ("tilt", "Tilt angle / rate"),
                 ("snr", "Target SNR"), ("cands", "Candidates")]
        self.cards = {}
        for i, (k, t) in enumerate(names):
            c = Card(t)
            self.cards[k] = c
            grid.addWidget(c, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)

    def set_video_mode(self, video: bool) -> None:
        """In MP4 mode the boresight is virtual (no PTZ camera)."""
        self.cards["track"].t.setText("Virtual pointing error" if video else "Tracking error")
        self.video = video

    def _state_color(self, s: str) -> None:
        self.state.setStyleSheet(f"background:{STATE_COLORS.get(s, '#94A3B8')};")

    def update_packet(self, p: dict, urad_per_px: float) -> None:
        """Refresh from a frame packet (+ periodic metrics)."""
        self.state.setText(f"  {p['state']}")
        self._state_color(p["state"])
        c = self.cards
        ce = p["centroid_err"]
        c["cent"].set(_f(ce, 3, " px"), f"{_f(ce * urad_per_px if ce == ce else None, 1)} µrad"
                      if ce == ce else "this frame", None if ce != ce else ce <= 10)
        te = p["track_err"] if p["state"] == "LOCKED" else float("nan")
        c["track"].set(_f(te, 2, " px"), ("|truth − virtual boresight|" if getattr(self, "video", False)
                                         else "|true beacon − boresight|") if te == te else
                       "LOCKED frames only", None if te != te else te <= 10)
        c["pan"].set(f"{p['pointing_deg'][0]:+.3f}°", f"{p['rate']:+.2f} °/s")
        c["tilt"].set(f"{p['pointing_deg'][1]:+.3f}°", f"{p['rate_t']:+.2f} °/s")
        c["snr"].set(_f(p["snr"], 1) if p["snr"] else "—")
        c["cands"].set(str(len(p["cands"])))
        c["ms"].set(_f(p["proc_ms"], 2, " ms"), "perception + tracking + control")
        m = p.get("metrics")
        if not m:
            return
        acq = m.get("acquisition_time_s")
        c["acq"].set(_f(acq, 2, " s"), "PS ≤ 2 s", None if acq != acq else acq <= 2.0)
        ra = m["reacquisition"]
        c["reacq"].set(str(ra["count"]), f"last {_f(ra['events'][-1]['duration_s'], 2, ' s')}"
                       if ra["events"] else ("lost — recovering" if ra["unrecovered_at_end"] else
                                             "none"),
                       None if not ra["events"] else ra["max_s"] <= 1.0)
        ret, loss = m.get("lock_retention"), m.get("target_loss")
        c["ret"].set(_f(None if ret is None else 100 * ret, 2, " %"), "post-acquisition")
        c["loss"].set(_f(None if loss is None else 100 * loss, 2, " %"), "PS < 5 %",
                      None if loss is None or loss != loss else loss < 0.05)
        fps = m["processing_fps"]
        c["fps"].set(_f(fps, 0), "PS ≥ 20 FPS", fps >= 20)
