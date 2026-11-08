# ui/settings_dialog.py — диалог настроек: тема, графики, чеки, налог.

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.summary import NPD_LIMIT_RUB, NPD_RATES
from services.settings import Settings, normalize


class SettingsDialog(QDialog):
    """Редактирует копию Settings; снаружи забирают result_settings()."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = deepcopy(settings)
        self.setWindowTitle("Настройки")
        self.resize(520, 420)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- внешний вид ---
        appearance = QWidget()
        form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Системная", "system")
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Тёмная", "dark")
        form.addRow("Тема", self.theme_combo)
        self.line_chart_check = QCheckBox("График поступлений по дням")
        self.pie_chart_check = QCheckBox("Круговая диаграмма по источникам")
        self.treemap_check = QCheckBox("Treemap")
        form.addRow(self.line_chart_check)
        form.addRow(self.pie_chart_check)
        form.addRow(self.treemap_check)
        tabs.addTab(appearance, "Внешний вид")

        # --- чеки ---
        receipts = QWidget()
        receipts_form = QFormLayout(receipts)
        self.receipt_name_edit = QLineEdit()
        receipts_form.addRow("Услуга в чеке", self.receipt_name_edit)
        self.presets_edit = QPlainTextEdit()
        self.presets_edit.setPlaceholderText("По одному названию на строку")
        receipts_form.addRow("Шаблоны услуг", self.presets_edit)
        self.confirm_send_check = QCheckBox("Спрашивать подтверждение перед отправкой")
        receipts_form.addRow(self.confirm_send_check)
        note = QLabel(
            "Наименование подставляется при создании чека; его можно изменить "
            "в диалоге отправки. Уже отправленные чеки не меняются."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")
        receipts_form.addRow(note)
        tabs.addTab(receipts, "Чеки")

        # --- налог ---
        tax = QWidget()
        tax_form = QFormLayout(tax)
        rate_row = QHBoxLayout()
        self.tax_rate_spin = QDoubleSpinBox()
        self.tax_rate_spin.setRange(0.0, 100.0)
        self.tax_rate_spin.setDecimals(4)
        self.tax_rate_spin.setSingleStep(0.5)
        self.tax_rate_spin.setSuffix(" %")
        rate_row.addWidget(self.tax_rate_spin, 1)
        for rate in NPD_RATES:
            button = QPushButton(f"{rate:.0f}%")
            button.setMaximumWidth(60)
            button.clicked.connect(lambda _=False, value=rate: self.tax_rate_spin.setValue(value))
            rate_row.addWidget(button)
        tax_form.addRow("Ставка налога", rate_row)
        tax_note = QLabel(
            f"Оценка налога НПД. Ставки ФНС: 4% с физлиц, 6% с юрлиц и ИП. "
            f"Лимит НПД — {NPD_LIMIT_RUB:,.0f} ₽/год.".replace(",", " ")
        )
        tax_note.setWordWrap(True)
        tax_note.setObjectName("hint")
        tax_form.addRow(tax_note)
        tabs.addTab(tax, "Налог")

        layout.addWidget(tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------------------------------------------------------------- данные
    def _load(self) -> None:
        index = self.theme_combo.findData(self._settings.theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.line_chart_check.setChecked(self._settings.show_line_chart)
        self.pie_chart_check.setChecked(self._settings.show_pie_chart)
        self.treemap_check.setChecked(self._settings.show_treemap)
        self.receipt_name_edit.setText(self._settings.receipt_name)
        self.presets_edit.setPlainText("\n".join(self._settings.receipt_name_presets))
        self.confirm_send_check.setChecked(self._settings.confirm_before_send)
        self.tax_rate_spin.setValue(self._settings.tax_rate)

    def _on_accept(self) -> None:
        self._settings.theme = self.theme_combo.currentData()
        self._settings.show_line_chart = self.line_chart_check.isChecked()
        self._settings.show_pie_chart = self.pie_chart_check.isChecked()
        self._settings.show_treemap = self.treemap_check.isChecked()
        self._settings.receipt_name = self.receipt_name_edit.text()
        self._settings.receipt_name_presets = [
            line.strip()
            for line in self.presets_edit.toPlainText().splitlines()
            if line.strip()
        ]
        self._settings.confirm_before_send = self.confirm_send_check.isChecked()
        self._settings.tax_rate = self.tax_rate_spin.value()
        normalize(self._settings)
        self.accept()

    def result_settings(self) -> Settings:
        return self._settings
