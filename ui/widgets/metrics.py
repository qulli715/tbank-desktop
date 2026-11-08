# ui/widgets/metrics.py — карточки метрик (Сумма, Количество, Средний, Мин, Макс).

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.analytics import format_rub


class MetricCard(QFrame):
    """Одна карточка: заголовок сверху, значение снизу."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("metricValue")
        self.value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for label in (self.title_label, self.value_label):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setMinimumWidth(0)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class MetricsRow(QWidget):
    """Пять метрик в ряд."""

    TITLES = ("Сумма", "Количество", "Средний чек", "Минимум", "Максимум")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.cards = [MetricCard(title) for title in self.TITLES]
        for card in self.cards:
            layout.addWidget(card, 1)

    def set_metrics(self, metrics: dict) -> None:
        self.cards[0].set_value(format_rub(metrics["total_rub"]))
        self.cards[1].set_value(str(metrics["count"]))
        self.cards[2].set_value(format_rub(metrics["avg_rub"]))
        self.cards[3].set_value(format_rub(metrics["min_rub"]) if metrics["count"] else "—")
        self.cards[4].set_value(format_rub(metrics["max_rub"]) if metrics["count"] else "—")
