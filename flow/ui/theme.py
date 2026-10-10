"""One dark theme for the windows, matching the floating panel."""

from __future__ import annotations

BG = "#141417"
SURFACE = "#1b1b20"
SURFACE_2 = "#232329"
BORDER = "#2e2e36"
TEXT = "#ececf0"
DIM = "#9a9ca4"
ACCENT = "#6d6ef0"
ACCENT_TEXT = "#ffffff"
DANGER = "#ef4444"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 10pt;
}}
QLabel[hint="true"] {{ color: {DIM}; font-size: 9pt; }}
QLabel[heading="true"] {{ font-size: 15pt; font-weight: 600; }}
QWidget[card="true"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 14px;
}}
QWidget[card="true"] QLabel {{ background: transparent; }}

QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 16px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {DIM};
}}

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTableWidget {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {DIM}; }}
QPushButton:default, QPushButton[primary="true"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 600;
}}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: {ACCENT_TEXT}; }}

QHeaderView::section {{
    background: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    color: {DIM};
}}
QTableWidget {{ gridline-color: {BORDER}; }}
QTableWidget::item:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}

QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    padding: 7px 14px;
    margin-right: 4px;
    border-radius: 8px;
    color: {DIM};
}}
QTabBar::tab:selected {{ background: {SURFACE_2}; color: {TEXT}; }}

QListWidget#nav {{
    background: {SURFACE};
    border: none;
    border-right: 1px solid {BORDER};
    padding: 10px 8px;
    font-size: 10.5pt;
}}
QListWidget#nav::item {{ padding: 9px 12px; border-radius: 8px; color: {DIM}; }}
QListWidget#nav::item:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}
QListWidget#nav::item:hover:!selected {{ background: {SURFACE_2}; color: {TEXT}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollArea {{ border: none; }}
"""
