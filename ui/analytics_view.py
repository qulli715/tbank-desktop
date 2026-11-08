# ui/analytics_view.py — экран «Аналитика»: фильтры, метрики, графики, treemap, таблица.

from __future__ import annotations

import math
from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.analytics import (
    MSK,
    compute_metrics,
    filter_incomes,
    format_rub,
    group_by_day,
    group_by_source,
    matches_income_query,
)
from core.models import Income
from core.treemap import (
    DEFAULT_MAX_SOURCES,
    HIERARCHY_SOURCE,
    HIERARCHY_SOURCE_DAY,
    METRIC_AVG,
    METRIC_SUM,
    TreemapResult,
    build_treemap,
)
from services import receipts as receipts_service
from services.state import AppState
from storage.db import list_incomes, set_hidden
from ui.widgets.charts import LineChartWidget, PieChartWidget, TreemapWidget
from ui.widgets.income_table import IncomeTableModel, create_table
from ui.widgets.metrics import MetricsRow


class AnalyticsView(QWidget):
    """Главный экран: фильтры слева, метрики, графики, treemap и таблица справа."""

    dataChanged = Signal()
    importRequested = Signal()
    receiptsTransferred = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = AppState()
        self._all: list[Income] = []
        self.model: IncomeTableModel | None = None
        self._build_ui()
        self.reload()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        # --- левая панель фильтров ---
        filters = QGroupBox("Фильтры")
        filters.setFixedWidth(250)
        form = QFormLayout(filters)
        form.setLabelAlignment(Qt.AlignLeft)

        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd.MM.yyyy")

        self.amount_from = QDoubleSpinBox()
        self.amount_to = QDoubleSpinBox()
        for spin in (self.amount_from, self.amount_to):
            spin.setDecimals(0)
            spin.setSingleStep(500)
            spin.setMaximum(1_000_000_000)
            spin.setSuffix(" ₽")

        self.hide_rows_check = QCheckBox("Скрывать строки полностью")

        self.reset_button = QPushButton("Сбросить фильтры")
        self.reload_button = QPushButton("Обновить")
        self.reload_button.setToolTip("Перечитать данные из БД (F5)")
        self.import_button = QPushButton("Импорт CSV…")
        self.import_button.setToolTip("Загрузить выписку Т-Банка (Ctrl+O)")

        form.addRow("Период с", self.date_from)
        form.addRow("по", self.date_to)
        form.addRow("Сумма от", self.amount_from)
        form.addRow("до", self.amount_to)
        form.addRow(self.hide_rows_check)
        form.addRow(self.import_button)
        form.addRow(self.reset_button)
        form.addRow(self.reload_button)

        filters_hint = QLabel(
            "Скрытые пополнения не влияют на метрики.\n"
            "«Выбрать» — для переноса в «Мой налог»."
        )
        filters_hint.setWordWrap(True)
        filters_hint.setObjectName("hint")
        form.addRow(filters_hint)

        # --- правая часть: метрики сверху ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.metrics = MetricsRow()
        right_layout.addWidget(self.metrics)

        # --- графики ---
        charts = QWidget()
        charts_layout = QVBoxLayout(charts)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(4)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.line_chart = LineChartWidget()
        self.pie_chart = PieChartWidget()
        charts_row.addWidget(self._titled("Поступления по дням", self.line_chart), 1)
        charts_row.addWidget(self._titled("Источники", self.pie_chart), 1)
        charts_layout.addLayout(charts_row)

        # контролы treemap
        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(QLabel("Метрика"))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["Сумма", "Средний чек"])
        controls.addWidget(self.metric_combo)

        controls.addSpacing(10)
        controls.addWidget(QLabel("Иерархия"))
        self.hierarchy_combo = QComboBox()
        self.hierarchy_combo.addItems(["По источникам", "Источник → день"])
        controls.addWidget(self.hierarchy_combo)

        controls.addSpacing(10)
        controls.addWidget(QLabel("Мин. сумма источника"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0, 10_000_000)
        self.threshold_spin.setSingleStep(100)
        self.threshold_spin.setDecimals(0)
        self.threshold_spin.setValue(500)
        self.threshold_spin.setSuffix(" ₽")
        controls.addWidget(self.threshold_spin)

        controls.addStretch(1)
        charts_layout.addLayout(controls)

        self.treemap = TreemapWidget()
        charts_layout.addWidget(self.treemap, 1)

        self.treemap_info = QLabel("—")
        self.treemap_info.setObjectName("hint")
        charts_layout.addWidget(self.treemap_info)

        # --- нижняя часть: таблица ---
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        toolbar = QHBoxLayout()
        self.selection_label = QLabel("Выбрано: 0")
        self.select_all_button = QPushButton("Выбрать все")
        self.clear_selection_button = QPushButton("Снять выбор")
        self.transfer_button = QPushButton("Перенести в «Мой налог»")
        self.transfer_button.setEnabled(False)
        self.transfer_button.setToolTip("Поставить отмеченные поступления в очередь чеков")
        toolbar.addWidget(self.selection_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.select_all_button)
        toolbar.addWidget(self.clear_selection_button)
        toolbar.addWidget(self.transfer_button)
        bottom_layout.addLayout(toolbar)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Поиск по таблице: имя, сумма, дата, описание, категория…"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.filter_badge = QLabel()
        self.filter_badge.setObjectName("filterBadge")
        self.filter_badge.setVisible(False)
        self.reset_source_button = QPushButton("Сбросить фильтр")
        self.reset_source_button.setVisible(False)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.filter_badge)
        search_row.addWidget(self.reset_source_button)
        bottom_layout.addLayout(search_row)

        table, model = create_table()
        self.table = table
        self.model = model
        bottom_layout.addWidget(table, 1)

        self.status_label = QLabel("—")
        self.status_label.setObjectName("hint")
        bottom_layout.addWidget(self.status_label)

        inner = QSplitter(Qt.Vertical)
        inner.setChildrenCollapsible(False)
        inner.addWidget(charts)
        inner.addWidget(bottom)
        inner.setStretchFactor(0, 0)
        inner.setStretchFactor(1, 1)
        inner.setSizes([420, 360])
        right_layout.addWidget(inner, 1)

        root = QSplitter(Qt.Horizontal)
        root.setChildrenCollapsible(False)
        root.addWidget(filters)
        root.addWidget(right)
        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 1)
        root.setSizes([250, 1100])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(root)

        # --- сигналы ---
        for edit in (self.date_from, self.date_to):
            edit.dateChanged.connect(self._apply_filters)
        for spin in (self.amount_from, self.amount_to):
            spin.valueChanged.connect(self._apply_filters)
        self.hide_rows_check.toggled.connect(self._apply_filters)
        self.reset_button.clicked.connect(self._reset_filters)
        self.reload_button.clicked.connect(self.reload)
        self.import_button.clicked.connect(self.importRequested)
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_selection_button.clicked.connect(self._clear_selection)
        self.transfer_button.clicked.connect(self._transfer_selected)
        self.model.selectToggled.connect(self._on_select_toggled)
        self.model.hiddenToggled.connect(self._on_hidden_toggled)

        self.metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        self.hierarchy_combo.currentIndexChanged.connect(self._apply_filters)
        self.threshold_spin.valueChanged.connect(self._apply_filters)
        self.treemap.sourceClicked.connect(self._on_source_clicked)
        self.reset_source_button.clicked.connect(lambda: self._on_source_clicked(None))
        self.search_edit.textChanged.connect(lambda _text: self._apply_filters())

    @staticmethod
    def _titled(title: str, widget: QWidget) -> QWidget:
        box = QWidget()
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setObjectName("chartBox")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        label = QLabel(title)
        label.setObjectName("chartTitle")
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return box

    # --------------------------------------------------------------- данные
    def reload(self) -> None:
        """Перечитывает все пополнения из БД и обновляет экран."""
        self._all = list_incomes(include_hidden=True)
        self._update_bounds()
        self._apply_filters()

    def _update_bounds(self) -> None:
        if not self._all:
            return
        days = sorted({income.occurred_at.astimezone(MSK).date() for income in self._all})
        max_rub = max(income.amount_kopecks for income in self._all) / 100

        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.amount_to.blockSignals(True)
        self.date_from.setDate(QDate(days[0].year, days[0].month, days[0].day))
        self.date_to.setDate(QDate(days[-1].year, days[-1].month, days[-1].day))
        self.amount_to.setValue(math.ceil(max_rub))
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.amount_to.blockSignals(False)

    def _selected_dates(self) -> tuple[date, date]:
        return self.date_from.date().toPython(), self.date_to.date().toPython()

    def _metric(self) -> str:
        return METRIC_AVG if self.metric_combo.currentIndex() == 1 else METRIC_SUM

    def _hierarchy(self) -> str:
        if self._metric() == METRIC_AVG:
            return HIERARCHY_SOURCE
        return HIERARCHY_SOURCE_DAY if self.hierarchy_combo.currentIndex() == 1 else HIERARCHY_SOURCE

    def _apply_filters(self) -> None:
        if self.model is None:
            return
        date_from, date_to = self._selected_dates()
        date_amount = filter_incomes(
            self._all,
            date_from=date_from,
            date_to=date_to,
            amount_min_rub=self.amount_from.value(),
            amount_max_rub=self.amount_to.value(),
            include_hidden=True,
        )
        visible = [income for income in date_amount if not income.is_hidden]
        hide_rows = self.hide_rows_check.isChecked()
        query = self.search_edit.text()
        table_rows = [
            income
            for income in date_amount
            if (not income.is_hidden or not hide_rows)
            and (self.state.source_filter is None or income.source == self.state.source_filter)
            and matches_income_query(income, query)
        ]

        self.model.set_rows(table_rows)
        self.model.set_selected(self.state.selected)
        self.metrics.set_metrics(compute_metrics(visible))

        self.line_chart.set_data(group_by_day(visible))
        self.pie_chart.set_data(group_by_source(visible))
        treemap_data = build_treemap(
            visible,
            metric=self._metric(),
            hierarchy=self._hierarchy(),
            threshold_rub=self.threshold_spin.value(),
        )
        self.treemap.set_data(treemap_data)
        self.treemap.set_filter(self.state.source_filter)
        self._update_treemap_info(treemap_data)
        self._update_filter_badge()

        hidden = [income for income in date_amount if income.is_hidden]
        hidden_sum = sum(income.amount_kopecks for income in hidden) / 100
        filter_note = f" · фильтр: {self.state.source_filter}" if self.state.source_filter else ""
        self.status_label.setText(
            f"Показано: {len(table_rows)} из {len(self._all)} · "
            f"скрыто: {len(hidden)} на {format_rub(hidden_sum)} · "
            f"всего в базе: {len(self._all)}{filter_note}"
        )
        self._update_selection_label()
        self.dataChanged.emit()

    def _update_treemap_info(self, result: TreemapResult) -> None:
        if self._metric() == METRIC_AVG:
            metric_note = "средний чек"
        else:
            metric_note = "сумма"
        cap_note = (
            f" (показаны {DEFAULT_MAX_SOURCES} крупнейших)" if result.capped else ""
        )
        self.treemap_info.setText(
            f"Показано источников: {result.shown_sources}{cap_note}. "
            f"В «Прочее»: {result.other_sources} "
            f"(сумма {format_rub(result.other_total_rub)}, метрика — {metric_note})."
        )

    def _update_filter_badge(self) -> None:
        source = self.state.source_filter
        self.filter_badge.setVisible(source is not None)
        self.reset_source_button.setVisible(source is not None)
        if source is not None:
            self.filter_badge.setText(f"Фильтр по источнику: {source}")

    # -------------------------------------------------------------- действия
    def _on_metric_changed(self) -> None:
        if self._metric() == METRIC_AVG:
            self.hierarchy_combo.blockSignals(True)
            self.hierarchy_combo.setCurrentIndex(0)
            self.hierarchy_combo.blockSignals(False)
            self.hierarchy_combo.setEnabled(False)
        else:
            self.hierarchy_combo.setEnabled(True)
        self._apply_filters()

    def _on_source_clicked(self, source) -> None:
        self.state.source_filter = source
        self._apply_filters()

    def _reset_filters(self) -> None:
        self._update_bounds()
        self.amount_from.blockSignals(True)
        self.amount_from.setValue(0)
        self.amount_from.blockSignals(False)
        self.hide_rows_check.setChecked(False)
        self.state.source_filter = None
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._apply_filters()

    def _select_all(self) -> None:
        if self.model is None:
            return
        self.state.selected = {income.external_id for income in self.model.rows()}
        self.model.set_selected(self.state.selected)
        self._update_selection_label()

    def _clear_selection(self) -> None:
        self.state.selected.clear()
        if self.model is not None:
            self.model.set_selected(self.state.selected)
        self._update_selection_label()

    def _on_select_toggled(self, external_id: str, selected: bool) -> None:
        if selected:
            self.state.selected.add(external_id)
        else:
            self.state.selected.discard(external_id)
        self._update_selection_label()

    def _on_hidden_toggled(self, external_id: str, hidden: bool) -> None:
        set_hidden(external_id, hidden)
        for income in self._all:
            if income.external_id == external_id:
                income.is_hidden = hidden
                break
        self._apply_filters()

    def _update_selection_label(self) -> None:
        count = len(self.state.selected)
        total_kopecks = sum(
            income.amount_kopecks
            for income in self._all
            if income.external_id in self.state.selected
        )
        self.selection_label.setText(f"Выбрано: {count} на {format_rub(total_kopecks / 100)}")
        self.transfer_button.setEnabled(count > 0)

    def _transfer_selected(self) -> None:
        """Ставит отмеченные поступления в очередь чеков «Мой налог»."""
        if not self.state.selected:
            return
        try:
            inserted, already = receipts_service.enqueue(self.state.selected)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Мой налог", f"Не удалось перенести: {exc}")
            return

        QMessageBox.information(
            self,
            "Мой налог",
            f"Перенесено в очередь: {inserted}.\nУже были в очереди: {already}.",
        )
        self.state.selected.clear()
        if self.model is not None:
            self.model.set_selected(self.state.selected)
        self._update_selection_label()
        self.receiptsTransferred.emit()
