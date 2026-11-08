# ui/analytics_view.py — экран «Аналитика»: фильтры, метрики, сводка, графики, treemap,
# таблица с прямоугольным выделением, массовыми действиями и экспортом.

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
    QProgressBar,
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
    format_rub_exact,
    group_by_day,
    group_by_source,
    matches_income_query,
)
from core.models import Income
from core.summary import (
    current_year,
    npd_progress,
    receipt_label,
    receipt_summary,
    tax_estimate_rub,
    year_total_rub,
)
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
from services.settings import Settings
from services.state import AppState
from storage.db import list_incomes, set_hidden
from ui.widgets.charts import LineChartWidget, PieChartWidget, TreemapWidget
from ui.widgets.income_table import IncomeTableModel, create_table
from ui.widgets.metrics import MetricsRow


class AnalyticsView(QWidget):
    """Главный экран: фильтры слева, метрики/сводка/графики/таблица справа."""

    dataChanged = Signal()
    importRequested = Signal()
    receiptsTransferred = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.state = AppState()
        self._all: list[Income] = []
        self._statuses: dict[str, str] = {}
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
        self.without_receipt_check = QCheckBox("Только без чека")

        self.import_button = QPushButton("Импорт CSV…")
        self.import_button.setToolTip("Загрузить выписку Т-Банка (Ctrl+O)")
        self.reset_button = QPushButton("Сбросить фильтры")
        self.reload_button = QPushButton("Обновить")
        self.reload_button.setToolTip("Перечитать данные из БД (F5)")

        form.addRow("Период с", self.date_from)
        form.addRow("по", self.date_to)
        form.addRow("Сумма от", self.amount_from)
        form.addRow("до", self.amount_to)
        form.addRow(self.hide_rows_check)
        form.addRow(self.without_receipt_check)
        form.addRow(self.import_button)
        form.addRow(self.reset_button)
        form.addRow(self.reload_button)
        filters_hint = QLabel(
            "Скрытые пополнения не влияют на метрики.\n"
            "Протяни мышью по таблице — прямоугольное выделение."
        )
        filters_hint.setWordWrap(True)
        filters_hint.setObjectName("hint")
        form.addRow(filters_hint)

        # --- правая часть ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.metrics = MetricsRow()
        right_layout.addWidget(self.metrics)

        right_layout.addWidget(self._build_summary_strip())

        charts = QWidget()
        charts_layout = QVBoxLayout(charts)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(4)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.line_chart = LineChartWidget()
        self.pie_chart = PieChartWidget()
        self._line_box = self._titled("Поступления по дням", self.line_chart)
        self._pie_box = self._titled("Источники", self.pie_chart)
        charts_row.addWidget(self._line_box, 1)
        charts_row.addWidget(self._pie_box, 1)
        charts_layout.addLayout(charts_row)

        self.treemap_block = self._build_treemap_block()
        charts_layout.addWidget(self.treemap_block, 1)

        # --- нижняя часть ---
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        toolbar = QHBoxLayout()
        self.selection_label = QLabel("Выбрано: 0")
        self.mark_selected_button = QPushButton("Отметить выделенные")
        self.unmark_selected_button = QPushButton("Снять отметку")
        self.hide_selected_button = QPushButton("Скрыть выделенные")
        self.select_all_button = QPushButton("Выбрать все")
        self.clear_selection_button = QPushButton("Снять выбор")
        self.transfer_button = QPushButton("Перенести в «Мой налог»")
        for button in (
            self.mark_selected_button,
            self.unmark_selected_button,
            self.hide_selected_button,
        ):
            button.setEnabled(False)
        self.transfer_button.setEnabled(False)
        toolbar.addWidget(self.selection_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.mark_selected_button)
        toolbar.addWidget(self.unmark_selected_button)
        toolbar.addWidget(self.hide_selected_button)
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
        inner.setSizes([400, 400])
        self._charts = charts
        self._bottom = bottom
        self._inner = inner
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
        self.without_receipt_check.toggled.connect(self._apply_filters)
        self.reset_button.clicked.connect(self._reset_filters)
        self.reload_button.clicked.connect(self.reload)
        self.import_button.clicked.connect(self.importRequested)
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_selection_button.clicked.connect(self._clear_selection)
        self.mark_selected_button.clicked.connect(self._mark_selected)
        self.unmark_selected_button.clicked.connect(self._unmark_selected)
        self.hide_selected_button.clicked.connect(self._hide_selected)
        self.transfer_button.clicked.connect(self._transfer_selected)
        self.model.selectToggled.connect(self._on_select_toggled)
        self.model.hiddenToggled.connect(self._on_hidden_toggled)
        self.table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)

        self.metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        self.hierarchy_combo.currentIndexChanged.connect(self._apply_filters)
        self.threshold_spin.valueChanged.connect(self._apply_filters)
        self.treemap.sourceClicked.connect(self._on_source_clicked)
        self.reset_source_button.clicked.connect(lambda: self._on_source_clicked(None))
        self.search_edit.textChanged.connect(lambda _text: self._apply_filters())

        self.apply_settings(self.settings)

    def _build_summary_strip(self) -> QWidget:
        strip = QWidget()
        strip.setObjectName("summaryStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(18)

        self.sum_income = QLabel("Доход: —")
        self.sum_income.setObjectName("summaryValue")
        self.sum_tax = QLabel("Налог: —")
        self.sum_tax.setObjectName("summaryValue")
        self.sum_missing = QLabel("Без чека: —")
        self.sum_missing.setObjectName("summaryValue")
        self.sum_checks = QLabel("Чеки: —")
        self.limit_bar = QProgressBar()
        self.limit_bar.setRange(0, 100)
        self.limit_bar.setValue(0)
        self.limit_bar.setFixedWidth(170)
        self.limit_bar.setTextVisible(True)
        self.limit_bar.setFormat("НПД: —")

        layout.addWidget(self.sum_income)
        layout.addWidget(self.sum_tax)
        layout.addWidget(self.sum_missing)
        layout.addWidget(self.sum_checks)
        layout.addStretch(1)
        layout.addWidget(self.limit_bar)
        return strip

    def _build_treemap_block(self) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.addWidget(QLabel("Метрика"))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["Сумма", "Средний чек"])
        controls_layout.addWidget(self.metric_combo)
        controls_layout.addSpacing(10)
        controls_layout.addWidget(QLabel("Иерархия"))
        self.hierarchy_combo = QComboBox()
        self.hierarchy_combo.addItems(["По источникам", "Источник → день"])
        controls_layout.addWidget(self.hierarchy_combo)
        controls_layout.addSpacing(10)
        controls_layout.addWidget(QLabel("Мин. сумма источника"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0, 10_000_000)
        self.threshold_spin.setSingleStep(100)
        self.threshold_spin.setDecimals(0)
        self.threshold_spin.setValue(500)
        self.threshold_spin.setSuffix(" ₽")
        controls_layout.addWidget(self.threshold_spin)
        controls_layout.addStretch(1)
        layout.addWidget(controls)

        self.treemap = TreemapWidget()
        layout.addWidget(self.treemap, 1)
        self.treemap_info = QLabel("—")
        self.treemap_info.setObjectName("hint")
        layout.addWidget(self.treemap_info)
        return block

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
        """Перечитывает пополнения и статусы чеков из БД."""
        self._all = list_incomes(include_hidden=True)
        try:
            self._statuses = receipts_service.statuses()
        except Exception:  # noqa: BLE001
            self._statuses = {}
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
        only_without_receipt = self.without_receipt_check.isChecked()
        query = self.search_edit.text()
        table_rows = [
            income
            for income in date_amount
            if (not income.is_hidden or not hide_rows)
            and (self.state.source_filter is None or income.source == self.state.source_filter)
            and (not only_without_receipt or self._statuses.get(income.external_id) != "sent")
            and matches_income_query(income, query)
        ]

        self.model.set_statuses(self._statuses)
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
        self._update_summary(visible)

        hidden = [income for income in date_amount if income.is_hidden]
        hidden_sum = sum(income.amount_kopecks for income in hidden) / 100
        filter_note = f" · фильтр: {self.state.source_filter}" if self.state.source_filter else ""
        self.status_label.setText(
            f"Показано: {len(table_rows)} из {len(self._all)} · "
            f"скрыто: {len(hidden)} на {format_rub(hidden_sum)} · "
            f"всего в базе: {len(self._all)}{filter_note}"
        )
        self._update_selection_label()
        self._on_table_selection_changed()
        self.dataChanged.emit()

    def _update_summary(self, visible: list[Income]) -> None:
        summary = receipt_summary(visible, self._statuses)
        tax = tax_estimate_rub(summary["total_rub"], self.settings.tax_rate)
        rate_text = f"{self.settings.tax_rate:g}%"
        self.sum_income.setText(f"Доход: {format_rub(summary['total_rub'])}")
        self.sum_tax.setText(f"Налог ({rate_text}): {format_rub(tax)}")
        self.sum_missing.setText(
            f"Без чека: {summary['none_count']} на {format_rub(summary['none_rub'])}"
        )
        self.sum_checks.setText(
            f"Чеки: {summary['sent_count']} / {summary['total_count']} "
            f"(в очереди: {summary['queued_count']})"
        )
        year_total = year_total_rub(self._all, current_year())
        progress = npd_progress(year_total)
        self.limit_bar.setValue(min(100, int(round(progress))))
        self.limit_bar.setFormat(f"НПД: {progress:.1f}%")

    def _update_treemap_info(self, result: TreemapResult) -> None:
        metric_note = "средний чек" if self._metric() == METRIC_AVG else "сумма"
        cap_note = f" (показаны {DEFAULT_MAX_SOURCES} крупнейших)" if result.capped else ""
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
        self.without_receipt_check.setChecked(False)
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

    # ------------------------------------------ прямоугольное выделение
    def _selected_incomes(self) -> list[Income]:
        if self.model is None:
            return []
        selection = self.table.selectionModel()
        if selection is None:
            return []
        model_rows = self.model.rows()
        indexes = sorted(index.row() for index in selection.selectedRows())
        return [model_rows[index] for index in indexes if 0 <= index < len(model_rows)]

    def _on_table_selection_changed(self, *_args) -> None:
        has_selection = bool(self._selected_incomes())
        self.mark_selected_button.setEnabled(has_selection)
        self.unmark_selected_button.setEnabled(has_selection)
        self.hide_selected_button.setEnabled(has_selection)

    def _mark_selected(self) -> None:
        selected = self._selected_incomes()
        if not selected:
            return
        self.state.selected.update(income.external_id for income in selected)
        if self.model is not None:
            self.model.set_selected(self.state.selected)
        self._update_selection_label()

    def _unmark_selected(self) -> None:
        selected = self._selected_incomes()
        if not selected:
            return
        for income in selected:
            self.state.selected.discard(income.external_id)
        if self.model is not None:
            self.model.set_selected(self.state.selected)
        self._update_selection_label()

    def _hide_selected(self) -> None:
        selected = self._selected_incomes()
        if not selected:
            return
        for income in selected:
            set_hidden(income.external_id, True)
            income.is_hidden = True
        self._apply_filters()

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
        self.reload()
        self.receiptsTransferred.emit()

    # -------------------------------------------------------------- настройки
    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self._line_box.setVisible(settings.show_line_chart)
        self._pie_box.setVisible(settings.show_pie_chart)
        self.treemap_block.setVisible(settings.show_treemap)
        self._update_charts_layout()
        self._apply_filters()

    def _update_charts_layout(self) -> None:
        """Скрывает весь блок графиков, если все выключены, и отдаёт место таблице."""
        show_any = (
            self.settings.show_line_chart
            or self.settings.show_pie_chart
            or self.settings.show_treemap
        )
        self._charts.setVisible(show_any)
        if not show_any:
            return

        self._charts.updateGeometry()
        hint = self._charts.sizeHint().height()
        if hint <= 0:
            hint = 260
        hint = min(430, max(200, hint))
        total = self._inner.height()
        if total > 0:
            charts_height = max(1, min(hint, total - 220))
            self._inner.setSizes([charts_height, max(1, total - charts_height)])
        else:
            self._inner.setSizes([hint, 400])

    # ---------------------------------------------------------------- экспорт
    def export_data(self) -> tuple[list[str], list[list[str]]]:
        """Заголовки и строки текущей таблицы (для CSV)."""
        headers = ["Дата", "Сумма, ₽", "Источник", "Описание", "Категория", "Чек"]
        rows: list[list[str]] = []
        if self.model is None:
            return headers, rows
        for income in self.model.rows():
            rows.append(
                [
                    income.occurred_at.astimezone(MSK).strftime("%d.%m.%Y %H:%M"),
                    format_rub_exact(income.amount_kopecks / 100),
                    income.source or "",
                    income.description or "",
                    income.category or "",
                    receipt_label(self._statuses.get(income.external_id)),
                ]
            )
        return headers, rows
