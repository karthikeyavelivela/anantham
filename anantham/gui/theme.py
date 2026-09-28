"""Light theme: white background, navy text, cyan accent; state colours."""

NAVY = "#1B2A4A"
CYAN = "#0EA5E9"
GREEN = "#16A34A"
AMBER = "#F59E0B"
RED = "#DC2626"
GREY = "#94A3B8"
BG = "#FFFFFF"
PANEL = "#F8FAFC"
BORDER = "#CBD5E1"

STATE_COLORS = {"SEARCH": RED, "CANDIDATE": CYAN, "LOCKED": GREEN, "COAST": AMBER,
                "RECOVER": AMBER, "—": GREY}
STATE_RGB = {"SEARCH": (220, 38, 38), "CANDIDATE": (14, 165, 233), "LOCKED": (22, 163, 74),
             "COAST": (245, 158, 11), "RECOVER": (234, 88, 12)}

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {NAVY}; font-size: 10pt; }}
QMainWindow::separator {{ background: {BORDER}; width: 2px; height: 2px; }}
QToolBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; spacing: 6px; padding: 3px; }}
QPushButton {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 10px; }}
QPushButton:hover {{ border-color: {CYAN}; }}
QPushButton:checked {{ background: {CYAN}; color: white; border-color: {CYAN}; }}
QPushButton#primary {{ background: {CYAN}; color: white; border-color: {CYAN}; font-weight: bold; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 5px 12px; }}
QTabBar::tab:selected {{ background: {BG}; border-bottom-color: {BG}; color: {CYAN}; font-weight: bold; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; }}
QLabel#cardTitle {{ color: #475569; font-size: 8pt; background: transparent; }}
QLabel#cardValue {{ font-size: 13pt; font-weight: bold; background: transparent; }}
QLabel#cardSub {{ color: #64748B; font-size: 8pt; background: transparent; }}
QLabel#stateLabel {{ font-size: 20pt; font-weight: bold; color: white; border-radius: 6px; padding: 6px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ border: 1px solid {BORDER}; border-radius: 3px;
    padding: 2px 4px; background: white; }}
QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] {{
    border: 2px solid {RED}; color: {RED}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; margin-top: 8px; font-weight: bold; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; }}
QHeaderView::section {{ background: {NAVY}; color: white; padding: 3px; border: none; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QDockWidget::title {{ background: {PANEL}; padding: 4px; }}
"""
