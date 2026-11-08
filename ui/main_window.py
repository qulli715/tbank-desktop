# ui/main_window.py — главное окно приложения: вкладки «Аналитика» и «Мой налог».

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
)

import config
from services.csv_import import import_csv
from ui.analytics_view import AnalyticsView
from ui.nalog_view import NalogView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("tbank — пополнения")
        self.resize(1380, 880)

        self.tabs = QTabWidget()
        self.analytics = AnalyticsView()
        self.nalog = NalogView()
        self.tabs.addTab(self.analytics, "Аналитика")
        self.tabs.addTab(self.nalog, "Мой налог")
        self.setCentralWidget(self.tabs)

        self.analytics.importRequested.connect(self._import_csv)
        self.analytics.receiptsTransferred.connect(self._on_receipts_transferred)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.statusBar().showMessage(f"tbank {config.APP_VERSION} · БД: {config.DB_PATH}")
        self._build_menu()

    # ------------------------------------------------------------- навигация
    def _on_receipts_transferred(self) -> None:
        self.nalog.refresh()
        self.tabs.setCurrentWidget(self.nalog)

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.nalog:
            self.nalog.refresh()

    # ------------------------------------------------------------------ меню
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")

        import_action = QAction("Импорт CSV…", self)
        import_action.setShortcut("Ctrl+O")
        import_action.triggered.connect(self._import_csv)
        file_menu.addAction(import_action)

        reload_action = QAction("Обновить данные", self)
        reload_action.setShortcut("F5")
        reload_action.triggered.connect(self.analytics.reload)
        file_menu.addAction(reload_action)

        quit_action = QAction("Выход", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("Справка")
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # -------------------------------------------------------------- действия
    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите CSV-выписку Т-Банка",
            "",
            "CSV-выписки (*.csv);;Все файлы (*.*)",
        )
        if not path:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            stats = import_csv(path)
        except Exception as exc:  # noqa: BLE001 — понятная ошибка вместо падения
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self,
                "Ошибка импорта",
                f"Не удалось импортировать файл:\n{Path(path).name}\n\n{exc}",
            )
            return
        QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self,
            "Импорт завершён",
            f"Файл: {Path(path).name}\n\n"
            f"Всего строк: {stats['total']}\n"
            f"Новых: {stats['inserted']}\n"
            f"Дубликатов: {stats['skipped']}\n"
            f"Исключено: {stats['excluded']}",
        )
        self.analytics.reload()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "О программе",
            f"tbank — анализ пополнений\n\n"
            f"Версия {config.APP_VERSION}\n"
            f"PySide6 / Qt 6\n\n"
            f"База данных:\n{config.DB_PATH}",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self.nalog.shutdown()
        super().closeEvent(event)
