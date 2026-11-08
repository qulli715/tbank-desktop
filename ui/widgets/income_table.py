# ui/widgets/income_table.py — таблица пополнений: чекбоксы «Выбрать»/«Скрыто», сортировка.

from __future__ import annotations

from zoneinfo import ZoneInfo

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

import config
from core.analytics import format_rub_exact
from core.models import Income

_TZ = ZoneInfo(config.DISPLAY_TZ)

COL_SELECT, COL_HIDDEN, COL_DATE, COL_AMOUNT, COL_SOURCE, COL_DESCRIPTION = range(6)
COLUMNS = ("Выбрать", "Скрыто", "Дата", "Сумма", "Источник", "Описание")

_HIDDEN_BG = QColor("#eef1f5")
_HIDDEN_FG = QColor("#8b93a1")

_DATA_KEYS = {
    COL_DATE: lambda income: income.occurred_at,
    COL_AMOUNT: lambda income: income.amount_kopecks,
    COL_SOURCE: lambda income: income.source or "",
    COL_DESCRIPTION: lambda income: income.description,
}


class IncomeTableModel(QAbstractTableModel):
    """Модель данных таблицы. Хранит строки и множество выбранных external_id."""

    hiddenToggled = Signal(str, bool)  # external_id, hidden
    selectToggled = Signal(str, bool)  # external_id, selected

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Income] = []
        self._selected: set[str] = set()

    # --- данные ---
    def set_rows(self, rows: list[Income]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

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

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        income = self._rows[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if column == COL_DATE:
                return income.occurred_at.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")
            if column == COL_AMOUNT:
                return format_rub_exact(income.amount_kopecks / 100)
            if column == COL_SOURCE:
                return income.source
            if column == COL_DESCRIPTION:
                return income.description
            return None
        if role == Qt.CheckStateRole and column in (COL_SELECT, COL_HIDDEN):
            if column == COL_SELECT:
                return Qt.Checked if income.external_id in self._selected else Qt.Unchecked
            return Qt.Checked if income.is_hidden else Qt.Unchecked
        if role == Qt.TextAlignmentRole and column == COL_AMOUNT:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and income.is_hidden:
            return QBrush(_HIDDEN_FG)
        if role == Qt.BackgroundRole and income.is_hidden:
            return QBrush(_HIDDEN_BG)
        if role == Qt.FontRole and income.is_hidden:
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.ToolTipRole:
            return f"{income.description}\nИсточник: {income.source}\nID: {income.external_id}"
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
        key = _DATA_KEYS.get(column)
        if key is None:
            return
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=key, reverse=(order == Qt.DescendingOrder))
        self.layoutChanged.emit()


def create_table(parent: QWidget | None = None) -> tuple[QTableView, IncomeTableModel]:
    """Создаёт настроенный QTableView и модель к нему."""
    model = IncomeTableModel(parent)
    table = QTableView(parent)
    table.setModel(model)
    table.setSortingEnabled(True)
    table.sortByColumn(COL_DATE, Qt.DescendingOrder)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(26)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setStretchLastSection(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(COL_SELECT, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_HIDDEN, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_DATE, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_AMOUNT, QHeaderView.Fixed)
    header.setSectionResizeMode(COL_SOURCE, QHeaderView.Interactive)
    header.resizeSection(COL_SELECT, 66)
    header.resizeSection(COL_HIDDEN, 62)
    header.resizeSection(COL_DATE, 132)
    header.resizeSection(COL_AMOUNT, 118)
    header.resizeSection(COL_SOURCE, 210)
    return table, model
