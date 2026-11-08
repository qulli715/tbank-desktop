# ui/main_window.py — главное окно: вкладки, меню, импорт/экспорт, настройки, drag&drop.

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
)

import config
from services.csv_import import import_csv
from services.settings import Settings, load_settings, save_settings
from ui import theme
from ui.analytics_view import AnalyticsView
from ui.nalog_view import NalogView
from ui.settings_dialog import SettingsDialog
from ui.update_check import fetch_latest_release, is_newer


class _UpdateWorker(QThread):
    done = Signal(object)

    def run(self) -> None:  # noqa: D401
        self.done.emit(fetch_latest_release())


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or load_settings()
        self.setWindowTitle("tbank — пополнения")
        self.resize(1380, 880)
        self.setAcceptDrops(True)
        self._update_worker: _UpdateWorker | None = None

        self.tabs = QTabWidget()
        self.analytics = AnalyticsView(self.settings)
        self.nalog = NalogView(self.settings)
        self.tabs.addTab(self.analytics, "Аналитика")
        self.tabs.addTab(self.nalog, "Мой налог")
        self.setCentralWidget(self.tabs)

        self.analytics.importRequested.connect(self._import_csv_dialog)
        self.analytics.receiptsTransferred.connect(self._on_receipts_transferred)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.statusBar().showMessage(
            f"tbank {config.APP_VERSION} · БД: {config.DB_PATH} · тема: {theme.resolve(self.settings.theme)}"
        )
        self._build_menu()

    # ------------------------------------------------------------- навигация
    def _on_receipts_transferred(self) -> None:
        self.nalog.refresh()
        self.tabs.setCurrentWidget(self.nalog)

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.nalog:
            self.nalog.refresh()
        else:
            self.analytics.reload()

    # ------------------------------------------------------------------ меню
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")

        import_action = QAction("Импорт CSV…", self)
        import_action.setShortcut("Ctrl+O")
        import_action.triggered.connect(self._import_csv_dialog)
        file_menu.addAction(import_action)

        export_action = QAction("Экспорт таблицы в CSV…", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._export_csv)
        file_menu.addAction(export_action)

        reload_action = QAction("Обновить данные", self)
        reload_action.setShortcut("F5")
        reload_action.triggered.connect(self.analytics.reload)
        file_menu.addAction(reload_action)

        file_menu.addSeparator()
        settings_action = QAction("Настройки…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        data_action = QAction("Открыть папку данных", self)
        data_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.DATA_DIR)))
        )
        file_menu.addAction(data_action)

        log_action = QAction("Открыть лог", self)
        log_action.triggered.connect(self._open_log)
        file_menu.addAction(log_action)

        file_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("Справка")
        update_action = QAction("Проверить обновления", self)
        update_action.triggered.connect(self._check_updates)
        help_menu.addAction(update_action)
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # -------------------------------------------------------------- действия
    def _import_csv_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите CSV-выписку Т-Банка",
            "",
            "CSV-выписки (*.csv);;Все файлы (*.*)",
        )
        if path:
            self._import_csv_file(path)

    def _import_csv_file(self, path: str) -> None:
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
        self.nalog.refresh()

    def _export_csv(self) -> None:
        headers, rows = self.analytics.export_data()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт таблицы в CSV",
            "tbank-popolnennia.csv",
            "CSV-файлы (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(headers)
                writer.writerows(rows)
        except OSError as exc:
            QMessageBox.critical(self, "Экспорт", f"Не удалось сохранить файл:\n{exc}")
            return
        QMessageBox.information(self, "Экспорт", f"Сохранено строк: {len(rows)}\n{path}")

    def _open_log(self) -> None:
        if config.LOG_FILE.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.LOG_FILE)))
        else:
            QMessageBox.information(self, "Лог", f"Файл лога ещё не создан:\n{config.LOG_FILE}")

    # ------------------------------------------------------------- настройки
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._apply_settings(dialog.result_settings())

    def _apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        save_settings(settings)
        theme.apply(settings.theme)
        self.analytics.apply_settings(settings)
        self.nalog.apply_settings(settings)
        self.statusBar().showMessage(
            f"Настройки сохранены · тема: {theme.resolve(settings.theme)} · "
            f"ставка налога: {settings.tax_rate:g}%"
        )

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._csv_from_event(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        path = self._csv_from_event(event)
        if path is not None:
            event.acceptProposedAction()
            self._import_csv_file(path)

    @staticmethod
    def _csv_from_event(event) -> str | None:  # noqa: ANN001
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".csv"):
                return url.toLocalFile()
        return None

    # ------------------------------------------------------------- обновления
    def _check_updates(self) -> None:
        self.statusBar().showMessage("Проверяю обновления…")
        worker = _UpdateWorker(self)
        worker.done.connect(self._on_update_checked)
        worker.finished.connect(worker.deleteLater)
        self._update_worker = worker
        worker.start()

    def _on_update_checked(self, release) -> None:  # noqa: ANN001
        self.statusBar().showMessage(f"tbank {config.APP_VERSION} · БД: {config.DB_PATH}")
        if not release:
            QMessageBox.information(
                self,
                "Проверка обновлений",
                "Не удалось проверить обновления (нет сети или GitHub недоступен).",
            )
            return
        tag = release["tag"]
        if is_newer(tag, config.APP_VERSION):
            answer = QMessageBox.question(
                self,
                "Доступно обновление",
                f"Установлена версия {config.APP_VERSION}, доступна {tag}.\n\n"
                "Открыть страницу релиза?",
            )
            if answer == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(release["url"]))
        else:
            QMessageBox.information(
                self,
                "Проверка обновлений",
                f"У вас последняя версия: {config.APP_VERSION}.",
            )

    # ------------------------------------------------------------------ about
    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "О программе",
            f"tbank — анализ пополнений и чеки «Мой налог»\n\n"
            f"Версия {config.APP_VERSION}\n"
            f"PySide6 / Qt 6 · лицензия MIT\n\n"
            f"База данных:\n{config.DB_PATH}\n"
            f"Данные:\n{config.DATA_DIR}",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self.nalog.shutdown()
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.quit()
            self._update_worker.wait(2000)
        super().closeEvent(event)
