# main.py — точка входа десктоп-приложения tbank (PySide6).

from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

import config
from core.logging_setup import setup_logging
from storage.db import backup_db, init_db

STYLE = """
QMainWindow { background: #ffffff; }
QTabWidget::pane { border: 1px solid #e3e8ef; border-radius: 6px; top: -1px; }
QTabBar::tab { padding: 8px 20px; font-size: 13px; color: #4b5563; }
QTabBar::tab:selected { background: #eef3fb; border-bottom: 2px solid #2f6fdd; color: #111827; }
QGroupBox {
    font-weight: 600; border: 1px solid #e3e8ef; border-radius: 8px;
    margin-top: 12px; padding: 10px 8px 8px 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
#metricCard { background: #f8fafc; border: 1px solid #e3e8ef; border-radius: 10px; }
#metricTitle { color: #6b7280; font-size: 11px; }
#metricValue { color: #111827; font-size: 19px; font-weight: 700; }
#hint { color: #6b7280; font-size: 11px; }
#chartTitle { color: #374151; font-weight: 600; font-size: 12px; padding: 4px 6px 2px 6px; }
#chartBox { background: #ffffff; border: 1px solid #e3e8ef; border-radius: 8px; }
#filterBadge {
    color: #1d4ed8; background: #e8efff; border: 1px solid #c7d7fe;
    border-radius: 10px; padding: 2px 8px; font-size: 11px;
}
QTableView {
    background: #ffffff;
    border: 1px solid #e3e8ef; border-radius: 8px;
    alternate-background-color: #f7f9fc; color: #111827;
    selection-background-color: #dbe7fb; selection-color: #111827;
}
QHeaderView::section {
    background: #f2f4f8; border: none; border-bottom: 1px solid #e3e8ef;
    padding: 6px 8px; font-weight: 600; color: #4b5563;
}
QPushButton { padding: 6px 14px; border-radius: 6px; background: #f3f4f6; border: 1px solid #d7dce4; }
QPushButton:hover { background: #e9edf3; }
QPushButton:disabled { color: #9ca3af; background: #f7f8fa; }
QCheckBox::indicator, QTableView::indicator { width: 15px; height: 15px; }
QCheckBox::indicator:unchecked, QTableView::indicator:unchecked {
    border: 1px solid #b6bfcc; border-radius: 3px; background: #ffffff;
}
QCheckBox::indicator:checked, QTableView::indicator:checked {
    border: 1px solid #2f6fdd; border-radius: 3px; background: #2f6fdd;
}
"""


def _install_excepthook(logger: logging.Logger) -> None:
    def hook(exc_type, exc, traceback):  # noqa: ANN001
        logger.exception("Необработанная ошибка", exc_info=(exc_type, exc, traceback))
        QMessageBox.critical(None, "Ошибка", f"{exc_type.__name__}: {exc}")

    sys.excepthook = hook


def _light_palette() -> QPalette:
    """Явная светлая палитра — чтобы вид не зависел от тёмной темы Windows."""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#ffffff"))
    palette.setColor(QPalette.WindowText, QColor("#111827"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f7f9fc"))
    palette.setColor(QPalette.Text, QColor("#111827"))
    palette.setColor(QPalette.Button, QColor("#f3f4f6"))
    palette.setColor(QPalette.ButtonText, QColor("#111827"))
    palette.setColor(QPalette.Highlight, QColor("#dbe7fb"))
    palette.setColor(QPalette.HighlightedText, QColor("#111827"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#111827"))
    palette.setColor(QPalette.PlaceholderText, QColor("#9ca3af"))
    return palette


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    logger = logging.getLogger("main")

    backup_db()
    init_db()

    app = QApplication(argv)
    app.setApplicationName("tbank")
    app.setApplicationDisplayName("tbank — пополнения")
    app.setStyle("Fusion")
    app.setPalette(_light_palette())
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    _install_excepthook(logger)

    from ui.main_window import MainWindow

    window = MainWindow()

    if "--smoke" in argv:
        # Режим проверки: отрисовать окно и сохранить скриншот, не входя в цикл событий.
        index = argv.index("--smoke")
        target = argv[index + 1] if index + 1 < len(argv) else "smoke.png"
        window.resize(1380, 880)
        window.show()
        for _ in range(8):
            app.processEvents()
        window.grab().save(target)
        logger.info("smoke screenshot сохранён: %s", target)
        window.close()
        app.processEvents()
        return 0

    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
