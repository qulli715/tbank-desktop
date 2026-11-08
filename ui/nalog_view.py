# ui/nalog_view.py — вкладка «Мой налог»: сессия, SMS-вход, очередь, отправка чеков.

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config
from core.analytics import format_rub_exact
from services import receipts as receipts_service
from services.settings import Settings

QUEUE_COLUMNS = ("Источник", "Сумма", "Дата поступления", "Описание", "Статус", "Ошибка")
SENT_COLUMNS = ("Источник", "Сумма", "Дата поступления", "Дата отправки", "Услуга", "Ссылка на чек")

_ERROR_COLOR = QColor("#b91c1c")
_PENDING_COLOR = QColor("#6b7280")
_SENT_COLOR = QColor("#15803d")


class _Worker(QThread):
    """Универсальный фоновый вызов: функция -> результат."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D401
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 — ошибка уходит в UI
            self.failed.emit(str(exc))


class _SendWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, only_failed: bool, receipt_name: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._only_failed = only_failed
        self._receipt_name = receipt_name

    def run(self) -> None:  # noqa: D401
        try:
            results = receipts_service.send(
                self._only_failed,
                on_progress=lambda index, total, text: self.progress.emit(index, total, text),
                receipt_name=self._receipt_name,
            )
            self.done.emit(results)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class NalogView(QWidget):
    """Очередь чеков и отправка в ФНС через moy-nalog-api."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._authenticated = False
        self._sending = False
        self._challenge_token: str | None = None
        self._phone_sent = ""
        self._queue_rows: list[dict] = []
        self._sent_rows: list[dict] = []
        self._queue_visible: list[dict] = []
        self._sent_visible: list[dict] = []
        self._workers: list[QThread] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.session_label = QLabel("Проверяю сессию…")
        self.session_label.setObjectName("sessionStatus")
        self.logout_button = QPushButton("Выйти из «Мой налог»")
        self.logout_button.setVisible(False)
        top.addWidget(self.session_label, 1)
        top.addWidget(self.logout_button)
        layout.addLayout(top)

        # --- вход ---
        self.login_group = QGroupBox("Вход в «Мой налог» по SMS")
        login_layout = QVBoxLayout(self.login_group)
        phone_row = QHBoxLayout()
        phone_row.addWidget(QLabel("Телефон"))
        self.phone_edit = QLineEdit(config.NALOG_PHONE)
        self.phone_edit.setPlaceholderText("79001234567")
        self.phone_edit.setMaxLength(20)
        self.request_button = QPushButton("Получить код")
        phone_row.addWidget(self.phone_edit, 1)
        phone_row.addWidget(self.request_button)
        login_layout.addLayout(phone_row)

        code_row = QHBoxLayout()
        code_row.addWidget(QLabel("Код из SMS"))
        self.code_edit = QLineEdit()
        self.code_edit.setMaxLength(6)
        self.code_edit.setPlaceholderText("123456")
        self.code_edit.setEnabled(False)
        self.login_button = QPushButton("Войти")
        self.login_button.setEnabled(False)
        code_row.addWidget(self.code_edit, 1)
        code_row.addWidget(self.login_button)
        login_layout.addLayout(code_row)

        self.login_status = QLabel("")
        self.login_status.setWordWrap(True)
        self.login_status.setObjectName("hint")
        login_layout.addWidget(self.login_status)
        hint = QLabel(
            "Пароль и ИНН не хранятся. Сессия сохраняется в data\\.moy-nalog-session.json."
        )
        hint.setObjectName("hint")
        login_layout.addWidget(hint)
        layout.addWidget(self.login_group)

        # --- подтверждение и кнопки отправки ---
        actions = QHBoxLayout()
        self.confirm_check = QCheckBox("Я подтверждаю отправку в ФНС")
        self.queue_summary = QLabel("Очередь пуста")
        self.queue_summary.setObjectName("hint")
        actions.addWidget(self.queue_summary)
        actions.addStretch(1)
        actions.addWidget(self.confirm_check)
        layout.addLayout(actions)

        buttons = QHBoxLayout()
        self.send_button = QPushButton("Создать чеки")
        self.retry_button = QPushButton("Повторить упавшие")
        self.delete_button = QPushButton("Убрать из очереди")
        self.delete_button.setEnabled(False)
        self.delete_button.setToolTip(
            "Удаляет выбранный чек из очереди (отправленные не удаляются)"
        )
        self.refresh_button = QPushButton("Обновить очередь")
        self.send_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.retry_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.refresh_button)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.send_status = QLabel("")
        self.send_status.setObjectName("hint")
        self.send_status.setVisible(False)
        layout.addWidget(self.progress)
        layout.addWidget(self.send_status)

        # --- таблицы очереди и отправленных ---
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        queue_box = QGroupBox("Очередь")
        queue_layout = QVBoxLayout(queue_box)
        self.queue_search = QLineEdit()
        self.queue_search.setPlaceholderText("Поиск: имя, сумма, дата, описание…")
        self.queue_search.setClearButtonEnabled(True)
        queue_layout.addWidget(self.queue_search)
        self.queue_table = self._make_table(QUEUE_COLUMNS)
        queue_layout.addWidget(self.queue_table)
        splitter.addWidget(queue_box)

        sent_box = QGroupBox("Отправленные")
        sent_layout = QVBoxLayout(sent_box)
        self.sent_search = QLineEdit()
        self.sent_search.setPlaceholderText("Поиск: имя, сумма, дата, описание…")
        self.sent_search.setClearButtonEnabled(True)
        sent_layout.addWidget(self.sent_search)
        self.sent_table = self._make_table(SENT_COLUMNS)
        sent_layout.addWidget(self.sent_table)
        splitter.addWidget(sent_box)

        splitter.setSizes([380, 300])
        layout.addWidget(splitter, 1)

        # --- сигналы ---
        self.request_button.clicked.connect(self._request_code)
        self.login_button.clicked.connect(self._login)
        self.logout_button.clicked.connect(self._logout)
        self.refresh_button.clicked.connect(self.refresh)
        self.confirm_check.toggled.connect(self._refresh_buttons)
        self.send_button.clicked.connect(lambda: self._send(only_failed=False))
        self.retry_button.clicked.connect(lambda: self._send(only_failed=True))
        self.delete_button.clicked.connect(self._delete_selected)
        self.queue_search.textChanged.connect(lambda _text: self._fill_queue())
        self.sent_search.textChanged.connect(lambda _text: self._fill_sent())
        self.queue_table.itemSelectionChanged.connect(self._refresh_delete_button)
        self.sent_table.cellDoubleClicked.connect(self._open_receipt)

    @staticmethod
    def _make_table(columns: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(list(columns))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(24)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        return table

    # --------------------------------------------------------------- данные
    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings

    def refresh(self) -> None:
        """Перечитывает сессию и очередь."""
        try:
            self._authenticated = receipts_service.session_authenticated()
        except Exception:  # noqa: BLE001
            self._authenticated = False

        self.login_group.setVisible(not self._authenticated)
        self.logout_button.setVisible(self._authenticated)
        if self._authenticated:
            self.session_label.setText("✅ Сессия активна — загружаю профиль ФНС…")
            self.session_label.setStyleSheet("color: #15803d; font-weight: 600;")
            self._run_worker(receipts_service.fetch_profile, self._on_profile, self._on_profile_failed)
        else:
            self.session_label.setText("Вход не выполнен — нужен код из SMS.")
            self.session_label.setStyleSheet("color: #b45309; font-weight: 600;")

        self._queue_rows = receipts_service.queue()
        self._sent_rows = receipts_service.sent()
        self._fill_queue()
        self._fill_sent()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_queue = bool(self._queue_rows)
        has_errors = any(row["status"] == "error" for row in self._queue_rows)
        can_send = (
            self._authenticated
            and self.confirm_check.isChecked()
            and not self._sending
        )
        self.send_button.setEnabled(can_send and has_queue)
        self.retry_button.setEnabled(can_send and has_errors)
        self.refresh_button.setEnabled(not self._sending)
        self.request_button.setEnabled(not self._sending)
        self.login_button.setEnabled(
            not self._sending and self._challenge_token is not None
        )
        self.logout_button.setEnabled(not self._sending)

        self._refresh_delete_button()

        count, total_kopecks = len(self._queue_rows), sum(
            row["amount_kopecks"] for row in self._queue_rows
        )
        if count:
            self.queue_summary.setText(
                f"В очереди: {count} чеков на {format_rub_exact(total_kopecks / 100)}"
            )
        else:
            self.queue_summary.setText("Очередь пуста")

    # ------------------------------------------------------------- таблицы
    def _fill_queue(self) -> None:
        rows = [
            row
            for row in self._queue_rows
            if receipts_service.matches_query(row, self.queue_search.text())
        ]
        self._queue_visible = rows
        table = self.queue_table
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["source"] or "",
                format_rub_exact(row["amount_kopecks"] / 100),
                receipts_service.format_dt(row["occurred_at"]),
                row["description"] or "",
                receipts_service.status_label(row["status"]),
                row["error_message"] or "",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                if column == 5 and row["error_message"]:
                    item.setForeground(_ERROR_COLOR)
                    item.setToolTip(row["error_message"])
                elif column == 4:
                    item.setForeground(
                        _ERROR_COLOR if row["status"] == "error" else _PENDING_COLOR
                    )
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        self._refresh_delete_button()

    def _fill_sent(self) -> None:
        rows = [
            row
            for row in self._sent_rows
            if receipts_service.matches_query(row, self.sent_search.text())
        ]
        self._sent_visible = rows
        table = self.sent_table
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["source"] or "",
                format_rub_exact(row["amount_kopecks"] / 100),
                receipts_service.format_dt(row["occurred_at"]),
                receipts_service.format_dt(row["sent_at"]),
                row.get("receipt_name") or "—",
                row["receipt_url"] or "",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                if column == 5:
                    item.setForeground(QColor("#1d4ed8"))
                    if row["receipt_url"]:
                        item.setToolTip("Двойной клик — открыть чек в браузере")
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------- удаление из очереди
    def _selected_queue_rows(self) -> list[dict]:
        selection = self.queue_table.selectionModel()
        if selection is None:
            return []
        indexes = sorted(index.row() for index in selection.selectedRows())
        return [self._queue_visible[i] for i in indexes if 0 <= i < len(self._queue_visible)]

    def _refresh_delete_button(self) -> None:
        rows = [
            row
            for row in self._selected_queue_rows()
            if row.get("status") in receipts_service.QUEUE_STATUSES
        ]
        self.delete_button.setEnabled(bool(rows) and not self._sending)

    def _delete_selected(self) -> None:
        rows = [
            row
            for row in self._selected_queue_rows()
            if row.get("status") in receipts_service.QUEUE_STATUSES
        ]
        if not rows:
            return
        if len(rows) == 1:
            row = rows[0]
            what = (
                f"чек по «{row['source']}» на "
                f"{format_rub_exact(row['amount_kopecks'] / 100)}"
            )
        else:
            total = sum(row["amount_kopecks"] for row in rows) / 100
            what = f"{len(rows)} чек(ов) на {format_rub_exact(total)}"
        if (
            QMessageBox.question(
                self,
                "Убрать из очереди",
                f"Убрать из очереди {what}?\n\n"
                "Поступление останется в базе — чек можно будет создать позже.",
            )
            != QMessageBox.Yes
        ):
            return
        ids = [int(row["income_id"]) for row in rows]
        try:
            removed = receipts_service.remove_many_from_queue(ids)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Мой налог", f"Не удалось убрать из очереди: {exc}")
            return
        if removed != len(ids):
            QMessageBox.information(
                self,
                "Мой налог",
                "Часть записей не найдена или уже отправлена — очередь обновлена.",
            )
        self.refresh()

    def _open_receipt(self, row: int, column: int) -> None:
        item = self.sent_table.item(row, SENT_COLUMNS.index("Ссылка на чек"))
        if item is None or not item.text() or item.text() == "—":
            return
        QDesktopServices.openUrl(QUrl(item.text()))

    # --------------------------------------------------------------- вход
    def _request_code(self) -> None:
        phone = "".join(ch for ch in self.phone_edit.text() if ch.isdigit())
        if len(phone) != 11 or not phone.startswith("7"):
            self.login_status.setText("Телефон должен быть в формате 79001234567 (11 цифр).")
            return
        self._sending = True
        self._refresh_buttons()
        self.login_status.setText("Отправляю код…")

        def work():
            return receipts_service.request_code(phone)

        def okay(result: dict) -> None:
            self._sending = False
            self._challenge_token = result["challenge_token"]
            self._phone_sent = phone
            self.code_edit.setEnabled(True)
            self.code_edit.setFocus()
            expire = result.get("expire_in")
            suffix = f" Действует {expire} сек." if expire else ""
            self.login_status.setText("Код отправлен." + suffix)
            self._refresh_buttons()

        self._run_worker(work, okay, self._on_login_failed)

    def _login(self) -> None:
        if self._challenge_token is None:
            return
        code = self.code_edit.text().strip()
        if not code:
            self.login_status.setText("Введите код из SMS.")
            return
        self._sending = True
        self._refresh_buttons()
        self.login_status.setText("Проверяю код…")

        def work():
            return receipts_service.login(self._phone_sent, self._challenge_token, code)

        def okay(profile: dict) -> None:
            self._sending = False
            self._challenge_token = None
            self.code_edit.clear()
            self.code_edit.setEnabled(False)
            name = profile.get("name") or "—"
            self.login_status.setText(f"Вход выполнен: {name}")
            self.refresh()

        self._run_worker(work, okay, self._on_login_failed)

    def _logout(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Выйти из «Мой налог»",
                "Удалить сохранённую сессию ФНС? Понадобится новый код из SMS.",
            )
            != QMessageBox.Yes
        ):
            return
        try:
            receipts_service.logout()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Не удалось выйти", str(exc))
            return
        self.login_status.setText("Сессия удалена.")
        self.refresh()

    # ------------------------------------------------------------ отправка
    def _send(self, only_failed: bool) -> None:
        if not self.confirm_check.isChecked() or self._sending:
            return
        if only_failed:
            count = sum(1 for row in self._queue_rows if row["status"] == "error")
            title = f"Повторить {count} упавших чеков?"
        else:
            count = len(self._queue_rows)
            title = f"Создать {count} чеков в ФНС?"
        if count <= 0:
            return

        presets = list(self.settings.receipt_name_presets) or [self.settings.receipt_name]
        default_name = self.settings.receipt_name
        current = presets.index(default_name) if default_name in presets else 0
        name, accepted = QInputDialog.getItem(
            self,
            "Наименование услуги",
            "Услуга в чеке:",
            presets,
            current,
            True,
        )
        if not accepted:
            return
        name = (name or "").strip() or default_name

        if self.settings.confirm_before_send and (
            QMessageBox.question(
                self,
                "Отправка в ФНС",
                f"{title}\n\nНаименование услуги: «{name}».\n\nПродолжить?",
            )
            != QMessageBox.Yes
        ):
            return

        self._sending = True
        self.progress.setVisible(True)
        self.progress.setRange(0, max(1, count))
        self.progress.setValue(0)
        self.send_status.setVisible(True)
        self.send_status.setText("Отправляю чеки…")
        self._refresh_buttons()

        worker = _SendWorker(only_failed, name, self)
        worker.progress.connect(self._on_send_progress)
        worker.done.connect(self._on_send_done)
        worker.failed.connect(self._on_send_failed)
        worker.finished.connect(lambda: self._release_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _on_send_progress(self, index: int, total: int, text: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(index + 1, total))
        self.send_status.setText(text)

    def _on_send_done(self, results: list) -> None:
        self._sending = False
        self.progress.setVisible(False)
        sent = sum(1 for item in results if item["status"] == "sent")
        errors = sum(1 for item in results if item["status"] == "error")
        self.send_status.setText(f"Готово: отправлено {sent}, ошибок {errors}.")
        QMessageBox.information(
            self, "Отправка завершена", f"Отправлено: {sent}.\nОшибок: {errors}."
        )
        self.refresh()

    def _on_send_failed(self, message: str) -> None:
        self._sending = False
        self.progress.setVisible(False)
        self.send_status.setText(f"Ошибка отправки: {message}")
        QMessageBox.critical(self, "Ошибка отправки", message)
        self.refresh()

    # ------------------------------------------------------------- профиль
    def _on_profile(self, profile: dict) -> None:
        name = profile.get("name") or "—"
        inn = profile.get("inn") or "—"
        self.session_label.setText(f"✅ Авторизован как {name} (ИНН: {inn})")

    def _on_profile_failed(self, message: str) -> None:
        self.session_label.setText(f"✅ Сессия активна (профиль ФНС недоступен: {message})")

    def _on_login_failed(self, message: str) -> None:
        self._sending = False
        self.login_status.setText(self._error_text(message))
        self._refresh_buttons()

    @staticmethod
    def _error_text(message: str) -> str:
        return receipts_service.sms_error_text(Exception(message))

    # ------------------------------------------------------------- воркеры
    def _run_worker(self, fn, on_done, on_failed) -> None:
        worker = _Worker(fn, self)
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        worker.finished.connect(lambda: self._release_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _release_worker(self, worker: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def shutdown(self) -> None:
        """Останавливает фоновые потоки перед выходом (сеть/отправка)."""
        for worker in list(self._workers):
            worker.quit()
            if not worker.wait(1500):
                worker.terminate()
                worker.wait(500)
        self._workers.clear()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)
