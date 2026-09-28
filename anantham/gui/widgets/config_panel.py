"""Configuration panel generated from the schema metadata (PS ranges shown, violations red)."""

from __future__ import annotations

import dataclasses

import yaml
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import Config, ConfigError, from_dict, to_dict, validate
from ...config.schema import DistractorConfig

TABS = [
    ("Scene && Camera", ["camera"]),
    ("Target", ["target", "target.blink"]),
    ("Disturbances", ["disturbances", "disturbances.turbulence"]),
    ("Tracker", ["acquisition", "perception", "tracker", "control"]),
    ("Run", ["run"]),
]
LIST_FIELDS = {"target.waypoints", "target.distractors", "target.occlusions"}


def _get(obj, path):
    for p in path.split(".") if path else []:
        obj = getattr(obj, p)
    return obj


def _pretty(name: str) -> str:
    return name.replace("_", " ").replace(" px", " (px)").replace(" deg s", " (°/s)") \
        .replace(" deg", " (°)").replace(" hz", " (Hz)").replace(" dn", " (DN)").capitalize()


class ConfigPanel(QWidget):
    """Tabbed editor over every config field."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widgets: dict[str, tuple] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.issues = QLabel("")
        self.issues.setWordWrap(True)
        self.issues.setStyleSheet("color:#DC2626; font-size:8pt;")
        lay.addWidget(self.issues)
        base = Config()
        for title, sections in TABS:
            page = QWidget()
            form = QFormLayout(page)
            form.setVerticalSpacing(3)
            for sec in sections:
                obj = _get(base, sec)
                if sec.count(".") or len(sections) > 1:
                    hdr = QLabel(sec.split(".")[-1].upper())
                    hdr.setStyleSheet("font-weight:bold; color:#0EA5E9; margin-top:6px;")
                    form.addRow(hdr)
                if sec == "target":
                    self.count = QSpinBox()
                    self.count.setRange(1, 8)
                    self.count.setToolTip("PS: number of targets 1 (mandatory), multiple optional")
                    self.count.valueChanged.connect(self._count_changed)
                    form.addRow("Number of targets", self.count)
                for f in dataclasses.fields(obj):
                    if dataclasses.is_dataclass(getattr(obj, f.name)):
                        continue
                    self._add_field(form, f"{sec}.{f.name}", f, getattr(obj, f.name))
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setWidget(page)
            self.tabs.addTab(sc, title)
        self.set_config(base)

    # ---------------------------------------------------------------- widgets
    def _add_field(self, form, path, f, default):
        m = f.metadata
        if path in LIST_FIELDS:
            w = QLineEdit()
            w.editingFinished.connect(self._on_change)
            kind = "list"
        elif isinstance(default, bool):
            w = QCheckBox()
            w.toggled.connect(self._on_change)
            kind = "bool"
        elif m.get("choices"):
            w = QComboBox()
            w.addItems(list(m["choices"]))
            w.currentIndexChanged.connect(self._on_change)
            kind = "choice"
        elif isinstance(default, int) and not isinstance(default, bool):
            w = QSpinBox()
            w.setRange(int(m.get("hard_lo") if m.get("hard_lo") is not None else -10 ** 9),
                       int(m.get("hard_hi") if m.get("hard_hi") is not None else 10 ** 9))
            w.valueChanged.connect(self._on_change)
            kind = "int"
        elif isinstance(default, float):
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(float(m.get("hard_lo") if m.get("hard_lo") is not None else -1e9),
                       float(m.get("hard_hi") if m.get("hard_hi") is not None else 1e9))
            w.setSingleStep(0.1)
            w.valueChanged.connect(self._on_change)
            kind = "float"
        else:  # str or Optional
            w = QLineEdit()
            w.editingFinished.connect(self._on_change)
            kind = "opt" if default is None or path.endswith(("contrast", "brightness")) else "str"
        lo, hi = m.get("ps_lo"), m.get("ps_hi")
        ps = ""
        if lo is not None and hi is not None:
            ps = f"PS {lo:g}" if lo == hi else f"PS {lo:g}–{hi:g}"
        elif lo is not None:
            ps = f"PS ≥ {lo:g}"
        elif hi is not None:
            ps = f"PS ≤ {hi:g}"
        tip = m.get("note", "") + (f" [{m.get('unit')}]" if m.get("unit") else "")
        w.setToolTip(tip)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(w, 1)
        if ps:
            lab = QLabel(ps)
            lab.setStyleSheet("color:#64748B; font-size:8pt;")
            rl.addWidget(lab)
        label = QLabel(_pretty(f.name))
        label.setToolTip(tip)
        form.addRow(label, row)
        self.widgets[path] = (w, kind)

    # ---------------------------------------------------------------- get / set
    def set_config(self, cfg: Config) -> None:
        """Populate all widgets from ``cfg``."""
        self._loading = True
        for path, (w, kind) in self.widgets.items():
            v = _get(cfg, path)
            if kind == "bool":
                w.setChecked(bool(v))
            elif kind == "choice":
                w.setCurrentText(str(v))
            elif kind in ("int", "float"):
                w.setValue(v)
            elif kind == "list":
                w.setText(yaml.safe_dump(v, default_flow_style=True).strip())
            elif kind == "opt":
                w.setText("" if v is None else str(v))
            else:
                w.setText(str(v))
        self.count.setValue(1 + len(cfg.target.distractors))
        self._loading = False
        self._validate()

    def to_dict(self) -> dict:
        """Current widget values as a nested dict."""
        out: dict = {}
        for path, (w, kind) in self.widgets.items():
            if kind == "bool":
                v = w.isChecked()
            elif kind == "choice":
                v = w.currentText()
            elif kind in ("int", "float"):
                v = w.value()
            elif kind == "list":
                v = yaml.safe_load(w.text() or "[]") or []
            elif kind == "opt":
                t = w.text().strip()
                v = None if t in ("", "None", "none") else yaml.safe_load(t)
            else:
                v = w.text()
            d = out
            parts = path.split(".")
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            d[parts[-1]] = v
        return out

    def get_config(self) -> Config:
        """Build a Config (raises ConfigError on type errors)."""
        return from_dict(self.to_dict())

    def set_start(self, x: float, y: float) -> None:
        """Minimap click → user start position."""
        self.widgets["target.start"][0].setCurrentText("user")
        self.widgets["target.start_x_px"][0].setValue(x)
        self.widgets["target.start_y_px"][0].setValue(y)

    def _count_changed(self, n: int) -> None:
        if getattr(self, "_loading", False):
            return
        w = self.widgets["target.distractors"][0]
        cur = yaml.safe_load(w.text() or "[]") or []
        dflt = to_dict(DistractorConfig())
        cur = (cur + [dflt] * n)[: n - 1]
        w.setText(yaml.safe_dump(cur, default_flow_style=True).strip())
        self._on_change()

    def _on_change(self, *_):
        if getattr(self, "_loading", False):
            return
        self._validate()
        self.changed.emit()

    def _validate(self) -> list:
        for w, _k in self.widgets.values():
            w.setProperty("invalid", False)
        try:
            issues = validate(self.get_config())
        except (ConfigError, yaml.YAMLError) as exc:
            self.issues.setText(f"✖ {exc}")
            return [exc]
        for i in issues:
            if i.path in self.widgets:
                w = self.widgets[i.path][0]
                w.setProperty("invalid", True)
                w.setToolTip(str(i))
        for w, _k in self.widgets.values():
            w.style().unpolish(w)
            w.style().polish(w)
        self.issues.setText("\n".join(f"✖ {i.path}: {i.message}" for i in issues[:6]))
        return issues

    def issues_list(self) -> list:
        """Current validation issues."""
        return self._validate()
