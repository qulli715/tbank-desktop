# ui/widgets/income_table.py — таблица пополнений: чекбоксы, статус чека,
# прямоугольное выделение мышью (как в Проводнике) и сортировка.

from __future__ import annotations

from zoneinfo import ZoneInfo

from PySide6.QtCore import QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QRubberBand,
    QTableView,
    QWidget,
)

import config
from core.analytics import format_rub_exact
from core.models import Income
from core.summary import receipt_label
from ui import theme

_TZ = ZoneInfo(config.DISPLAY_TZ)

COL_SELECT, COL_HIDDEN, COL_DATE, COL_AMOUNT, COL_SOURCE, COL_DESCRIPTION, COL_RECEIPT = range(7)
COLUMNS = ("Выбрать", "Скрыто", "Дата", "Сумма", "Источник", "Описание", "Чек")

_STATUS_SORT = {"нет": 0, "в очереди": 1, "ошибка": 2, "отправлен": 3}

_DATA_KEYS = {
    COL_DATE: lambda income: income.occurred_at,
    COL_AMOUNT: lambda income: income.amount_kopecks,
    COL_SOURCE: lambda income: income.source or "",
    COL_DESCRIPTION: lambda income: income.description,
}


class IncomeTableModel(QAbstractTableModel):
    """Модель данных таблицы. Хранит строки, выбранные external_id и статусы чеков."""

    hiddenToggled = Signal(str, bool)  # external_id, hidden
    selectToggled = Signal(str, bool)  # external_id, selected

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Income] = []
        self._selected: set[str] = set()
        self._statuses: dict[str, str] = {}

    # --- данные ---
    def set_rows(self, rows: list[Income]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_statuses(self, statuses: dict[str, str]) -> None:
        self._statuses = dict(statuses)
        if self._rows:
            self.dataChanged.emit(
                self.index(0, COL_RECEIPT),
                self.index(len(self._rows) - 1, COL_RECEIPT),
                [Qt.DisplayRole, Qt.ForegroundRole],
            )

    def set_selected(self, selected: set[str]) -> None:
        self._selected = set(selected)
        if self._rows:
            self.dataChanged.emit(
                self.index(0, COL_SELECT),
                self.index(len(self._rows) - 1, COL_SELECT),
                [Qt.CheckStateRole],
            )

    def rows(self) -> list[Income]:
        return self._rows

    def selected_ids(self) -> set[str]:
        return set(self._selected)

    # --- QAbstractTableModel ---
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def _status_text(self, income: Income) -> str:
        return receipt_label(self._statuses.get(income.external_id))

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        income = self._rows[index.row()]
        column = index.column()
        colors = theme.colors()

        if role == Qt.DisplayRole:
            if column == COL_DATE:
                return income.occurred_at.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")
            if column == COL_AMOUNT:
                return format_rub_exact(income.amount_kopecks / 100)
            if column == COL_SOURCE:
                return income.source
            if column == COL_DESCRIPTION:
                return income.description
            if column == COL_RECEIPT:
                return self._status_text(income)
            return None
        if role == Qt.CheckStateRole and column in (COL_SELECT, COL_HIDDEN):
            if column == COL_SELECT:
                return Qt.Checked if income.external_id in self._selected else Qt.Unchecked
            return Qt.Checked if income.is_hidden else Qt.Unchecked
        if role == Qt.TextAlignmentRole and column in (COL_AMOUNT, COL_RECEIPT):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            if income.is_hidden:
                return QBrush(QColor(colors["hidden_fg"]))
            if column == COL_RECEIPT:
                status = self._statuses.get(income.external_id)
                if status == "sent":
                    return QBrush(QColor(colors["ok_text"]))
                if status in ("pending", "error"):
                    key = "error_text" if status == "error" else "warn_text"
                    return QBrush(QColor(colors[key]))
                return QBrush(QColor(colors["muted"]))
        if role == Qt.BackgroundRole and income.is_hidden:
            return QBrush(QColor(colors["hidden_bg"]))
        if role == Qt.FontRole and income.is_hidden:
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.ToolTipRole:
            status = self._status_text(income)
            return (
                f"{income.description}\nИсточник: {income.source}\n"
                f"Чек: {status}\nID: {income.external_id}"
            )
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() in (COL_SELECT, COL_HIDDEN):
            return base | Qt.ItemIsUserCheckable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        income = self._rows[index.row()]
        checked = bool(value == Qt.Checked or value == 2)
        if index.column() == COL_SELECT:
            if checked:
                self._selected.add(income.external_id)
            else:
                self._selected.discard(income.external_id)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.selectToggled.emit(income.external_id, checked)
            return True
        if index.column() == COL_HIDDEN:
            self.hiddenToggled.emit(income.external_id, checked)
            return True
        return False

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        if column == COL_RECEIPT:
            key = lambda income: _STATUS_SORT.get(  # noqa: E731
                receipt_label(self._statuses.get(income.external_id)), 0
            )
        else:
            key = _DATA_KEYS.get(column)
        if key is None:
            return
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=key, reverse=(order == Qt.DescendingOrder))
        self.layoutChanged.emit()


class IncomeTable(QTableView):
    """QTableView с прямоугольным выделением строк мышью (как в Проводнике)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rubber = QRubberBand(QRubberBand.Rectangle, self.viewport())
        self._origin = None
        self._band_active = False
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() in (COL_SELECT, COL_HIDDEN):
            self._origin = None
            super().mousePressEvent(event)
            return
        self._origin = event.position().toPoint()
        self._band_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint()
        if not self._band_active:
            if (pos - self._origin).manhattanLength() < QApplication.startDragDistance():
                return
            self._band_active = True
            self._rubber.show()
        self._autoscroll(pos)
        viewport_rect = self.viewport().rect()
        clamped = pos
        clamped.setX(max(0, min(pos.x(), viewport_rect.width() - 1)))
        clamped.setY(max(0, min(pos.y(), viewport_rect.height() - 1)))
        self._rubber.setGeometry(QRect(self._origin, clamped).normalized())

    def _autoscroll(self, pos) -> None:  # noqa: ANN001
        bar = self.verticalScrollBar()
        if pos.y() < 0:
            bar.setValue(bar.value() - bar.singleStep())
        elif pos.y() > self.viewport().height():
            bar.setValue(bar.value() + bar.singleStep())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._band_active:
            self._origin = None
            super().mouseReleaseEvent(event)
            return
        rect = self._rubber.geometry()
        self._rubber.hide()
        self._select_rows_in_rect(rect)
        self._origin = None
        self._band_active = False

    def _select_rows_in_rect(self, rect: QRect) -> None:
        model = self.model()
        if model is None:
            return
        sm = self.selectionModel()
        sm.clearSelection()
        first = last = None
        for row in range(model.rowCount()):
            row_rect = self.visualRect(model.index(row, COL_DATE))
            if rect.intersects(row_rect):
                if first is None:
                    first = row
                last = row
        if first is None or last is None:
            return
        selection = QItemSelection(
            model.index(first, 0), model.index(last, model.columnCount() - 1)
        )
        sm.select(selection, QItemSelectionModel.Select | QItemSelectionModel.Rows)


def create_table(parent: QWidget | None = None) -> tuple[IncomeTable, IncomeTableModel]:
    """Создаёт настроенную таблицу и модель к ней."""
    model = IncomeTableModel(parent)
    table = IncomeTable(parent)
    table.setModel(model)
    table.setSortingEnabled(True)
    table.sortByColumn(COL_DATE, Qt.DescendingOrder)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(26)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setStretchLastSection(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(COL_SELECT, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_HIDDEN, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_DATE, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_AMOUNT, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_SOURCE, QHeaderView.Interactive)
    header.setSectionResizeMode(COL_DESCRIPTION, QHeaderView.Stretch)
    header.setSectionResizeMode(COL_RECEIPT, QHeaderView.Fixed)
    header.resizeSection(COL_SELECT, 66)
    header.resizeSection(COL_HIDDEN, 62)
    header.resizeSection(COL_DATE, 132)
    header.resizeSection(COL_AMOUNT, 118)
    header.resizeSection(COL_SOURCE, 180)
    header.resizeSection(COL_RECEIPT, 100)
    return table, model
