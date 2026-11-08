# ui/theme.py — светлая/тёмная тема: палитра и стили (QSS).

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#ffffff",
    "panel": "#f8fafc",
    "border": "#e3e8ef",
    "text": "#111827",
    "muted": "#6b7280",
    "accent": "#2f6fdd",
    "alt": "#f7f9fc",
    "header": "#f2f4f8",
    "selection": "#dbe7fb",
    "button": "#f3f4f6",
    "button_hover": "#e9edf3",
    "input_bg": "#ffffff",
    "indicator": "#b6bfcc",
    "tab_selected": "#eef3fb",
    "badge_bg": "#e8efff",
    "badge_border": "#c7d7fe",
    "badge_text": "#1d4ed8",
    "hidden_bg": "#eef1f5",
    "hidden_fg": "#8b93a1",
    "table_bg": "#ffffff",
    "tooltip_bg": "#ffffff",
    "tooltip_text": "#111827",
    "chart_text": "#111827",
    "ok_text": "#15803d",
    "warn_text": "#6b7280",
    "error_text": "#b91c1c",
    "link": "#1d4ed8",
}

DARK = {
    "bg": "#1b1f24",
    "panel": "#222831",
    "border": "#323a45",
    "text": "#e5e7eb",
    "muted": "#9aa3af",
    "accent": "#6aa1ff",
    "alt": "#20262e",
    "header": "#262d36",
    "selection": "#2f4f7a",
    "button": "#262d36",
    "button_hover": "#2e3743",
    "input_bg": "#161a1f",
    "indicator": "#6b7480",
    "tab_selected": "#243040",
    "badge_bg": "#1e3a5f",
    "badge_border": "#2f5f9e",
    "badge_text": "#9ec5ff",
    "hidden_bg": "#252b33",
    "hidden_fg": "#7d8694",
    "table_bg": "#1b1f24",
    "tooltip_bg": "#222831",
    "tooltip_text": "#e5e7eb",
    "chart_text": "#e5e7eb",
    "ok_text": "#4ade80",
    "warn_text": "#9aa3af",
    "error_text": "#f87171",
    "link": "#6aa1ff",
}

COLORS = dict(LIGHT)

_QSS = """
QMainWindow {{ background: {bg}; }}
QWidget {{ color: {text}; }}
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px; top: -1px; background: {bg}; }}
QTabBar::tab {{ padding: 8px 20px; font-size: 13px; color: {muted}; background: transparent; }}
QTabBar::tab:selected {{ background: {tab_selected}; border-bottom: 2px solid {accent}; color: {text}; }}
QGroupBox {{
    font-weight: 600; border: 1px solid {border}; border-radius: 8px;
    margin-top: 12px; padding: 10px 8px 8px 8px; background: {bg};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {muted}; }}
#metricCard {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
#metricTitle {{ color: {muted}; font-size: 11px; }}
#metricValue {{ color: {text}; font-size: 19px; font-weight: 700; }}
#hint {{ color: {muted}; font-size: 11px; }}
#chartTitle {{ color: {muted}; font-weight: 600; font-size: 12px; padding: 4px 6px 2px 6px; }}
#chartBox {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}
#summaryStrip {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; }}
#summaryValue {{ color: {text}; font-size: 13px; font-weight: 700; }}
#filterBadge {{
    color: {badge_text}; background: {badge_bg}; border: 1px solid {badge_border};
    border-radius: 10px; padding: 2px 8px; font-size: 11px;
}}
QTableView {{
    background: {table_bg}; border: 1px solid {border}; border-radius: 8px;
    alternate-background-color: {alt}; color: {text};
    selection-background-color: {selection}; selection-color: {text};
}}
QHeaderView::section {{
    background: {header}; border: none; border-bottom: 1px solid {border};
    padding: 6px 8px; font-weight: 600; color: {muted};
}}
QPushButton {{
    padding: 6px 14px; border-radius: 6px; background: {button};
    border: 1px solid {border}; color: {text};
}}
QPushButton:hover {{ background: {button_hover}; }}
QPushButton:disabled {{ color: {muted}; background: {panel}; }}
QCheckBox::indicator, QTableView::indicator {{ width: 15px; height: 15px; }}
QCheckBox::indicator:unchecked, QTableView::indicator:unchecked {{
    border: 1px solid {indicator}; border-radius: 3px; background: {input_bg};
}}
QCheckBox::indicator:checked, QTableView::indicator:checked {{
    border: 1px solid {accent}; border-radius: 3px; background: {accent};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit {{
    background: {input_bg}; border: 1px solid {border}; border-radius: 6px;
    padding: 3px 6px; color: {text};
}}
QProgressBar {{
    border: 1px solid {border}; border-radius: 6px; text-align: center;
    background: {panel}; color: {text};
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}
QMenu {{ background: {bg}; border: 1px solid {border}; color: {text}; }}
QToolBar {{ background: transparent; border: none; spacing: 4px; }}
QToolButton {{
    padding: 6px 12px; border-radius: 6px; background: {button};
    border: 1px solid {border}; color: {text};
}}
QToolButton:hover {{ background: {button_hover}; }}
QToolButton:disabled {{ color: {muted}; background: {panel}; }}
QStatusBar {{ color: {muted}; }}
QToolTip {{ background: {tooltip_bg}; color: {tooltip_text}; border: 1px solid {border}; }}
"""


def palette(colors: dict) -> QPalette:
    result = QPalette()
    result.setColor(QPalette.Window, QColor(colors["bg"]))
    result.setColor(QPalette.WindowText, QColor(colors["text"]))
    result.setColor(QPalette.Base, QColor(colors["table_bg"]))
    result.setColor(QPalette.AlternateBase, QColor(colors["alt"]))
    result.setColor(QPalette.Text, QColor(colors["text"]))
    result.setColor(QPalette.Button, QColor(colors["button"]))
    result.setColor(QPalette.ButtonText, QColor(colors["text"]))
    result.setColor(QPalette.Highlight, QColor(colors["selection"]))
    result.setColor(QPalette.HighlightedText, QColor(colors["text"]))
    result.setColor(QPalette.ToolTipBase, QColor(colors["tooltip_bg"]))
    result.setColor(QPalette.ToolTipText, QColor(colors["tooltip_text"]))
    result.setColor(QPalette.PlaceholderText, QColor(colors["muted"]))
    return result


def resolve(theme: str, app: QApplication | None = None) -> str:
    """'system' -> фактическая тема по цветовой схеме ОС."""
    if theme in ("light", "dark"):
        return theme
    instance = app or QApplication.instance()
    try:
        scheme = instance.styleHints().colorScheme() if instance is not None else Qt.Light
    except Exception:  # noqa: BLE001
        scheme = Qt.Light
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def apply(theme: str, app: QApplication | None = None) -> str:
    """Применяет тему к приложению, запоминает текущие цвета. Возвращает actual."""
    global COLORS
    instance = app or QApplication.instance()
    actual = resolve(theme, instance)
    COLORS = dict(DARK if actual == "dark" else LIGHT)
    if instance is not None:
        instance.setStyle("Fusion")
        instance.setPalette(palette(COLORS))
        instance.setStyleSheet(_QSS.format(**COLORS))
    return actual


def colors() -> dict:
    return COLORS
