# ui/widgets/charts.py — нативные графики QPainter: линия, круговая, treemap.

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from core.analytics import format_rub
from core.treemap import TreemapNode, TreemapResult
from ui import theme

PALETTE = [
    "#4f7cff", "#2bb673", "#f2a33c", "#e05c5c", "#8b5cf6",
    "#14b8a6", "#ec4899", "#84cc16", "#f97316", "#06b6d4",
    "#a855f7", "#64748b",
]
OTHER_COLOR = "#9aa3af"


def _bg() -> QColor:
    return QColor(theme.colors()["bg"])


def _text() -> QColor:
    return QColor(theme.colors()["text"])


def _muted() -> QColor:
    return QColor(theme.colors()["muted"])


def _grid() -> QColor:
    return QColor(theme.colors()["border"])


def _accent() -> QColor:
    return QColor(theme.colors()["accent"])


def _compact_rub(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн ₽".replace(".0", "")
    if value >= 1_000:
        return f"{value / 1_000:.1f} тыс ₽".replace(".0", "")
    return f"{value:.0f} ₽"


class ChartWidget(QWidget):
    """Базовый виджет графика: белый фон, минимальная высота."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAutoFillBackground(False)

    def _begin_paint(self) -> QPainter:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), _bg())
        return painter

    def _draw_empty(self, painter: QPainter, text: str = "Нет данных") -> None:
        painter.setPen(QPen(_muted()))
        painter.drawText(self.rect(), Qt.AlignCenter, text)


# --------------------------------------------------------------------------- #
# Линия по дням
# --------------------------------------------------------------------------- #
class LineChartWidget(ChartWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[dict] = []

    def set_data(self, points: list[dict]) -> None:
        self._points = points
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = self._begin_paint()
        try:
            if not self._points:
                self._draw_empty(painter)
                return
            left, top, right, bottom = 62, 14, 12, 26
            area = QRectF(
                left,
                top,
                max(10.0, self.width() - left - right),
                max(10.0, self.height() - top - bottom),
            )
            values = [point["total_rub"] for point in self._points]
            max_value = max(values) or 1.0

            # сетка и подписи оси Y
            font = QFont(self.font())
            font.setPointSize(8)
            painter.setFont(font)
            for step in range(5):
                ratio = step / 4
                y = area.bottom() - ratio * area.height()
                painter.setPen(QPen(_grid(), 1))
                painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
                painter.setPen(QPen(_muted(), 1))
                painter.drawText(
                    QRectF(0, y - 8, left - 8, 16),
                    Qt.AlignRight | Qt.AlignVCenter,
                    _compact_rub(max_value * ratio),
                )

            count = len(self._points)
            def x_at(index: int) -> float:
                if count == 1:
                    return area.center().x()
                return area.left() + index * area.width() / (count - 1)

            def y_at(value: float) -> float:
                return area.bottom() - (value / max_value) * area.height()

            # заливка под линией
            path = QPainterPath()
            path.moveTo(x_at(0), area.bottom())
            for index, point in enumerate(self._points):
                path.lineTo(x_at(index), y_at(point["total_rub"]))
            path.lineTo(x_at(count - 1), area.bottom())
            path.closeSubpath()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(79, 124, 255, 38)))
            painter.drawPath(path)

            # линия и точки
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(_accent(), 2))
            for index in range(1, count):
                painter.drawLine(
                    QPointF(x_at(index - 1), y_at(self._points[index - 1]["total_rub"])),
                    QPointF(x_at(index), y_at(self._points[index]["total_rub"])),
                )
            painter.setBrush(QBrush(_bg()))
            painter.setPen(QPen(_accent(), 2))
            for index, point in enumerate(self._points):
                painter.drawEllipse(QPointF(x_at(index), y_at(point["total_rub"])), 3, 3)

            # подписи оси X (примерно 6 штук)
            painter.setPen(QPen(_muted(), 1))
            step = max(1, count // 6)
            for index in range(0, count, step):
                label = self._points[index]["date"].strftime("%d.%m")
                painter.drawText(
                    QRectF(x_at(index) - 24, area.bottom() + 4, 48, 18),
                    Qt.AlignHCenter | Qt.AlignTop,
                    label,
                )
        finally:
            painter.end()


# --------------------------------------------------------------------------- #
# Круговая по источникам
# --------------------------------------------------------------------------- #
class PieChartWidget(ChartWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sources: list[dict] = []

    def set_data(self, sources: list[dict]) -> None:
        self._sources = sources
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = self._begin_paint()
        try:
            if not self._sources:
                self._draw_empty(painter)
                return
            total = sum(item["total_rub"] for item in self._sources) or 1.0
            size = max(40.0, min(self.height() - 16, self.width() * 0.45))
            pie_rect = QRectF(10, (self.height() - size) / 2, size, size)

            start = 90 * 16
            for index, item in enumerate(self._sources):
                span = int(round(item["total_rub"] / total * 360 * 16))
                color = QColor(PALETTE[index % len(PALETTE)])
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawPie(pie_rect, start, -span)
                start -= span

            # легенда: сжимаем строки, чтобы всё влезло; лишние сворачиваем в «ещё N»
            legend_x = pie_rect.right() + 14
            count = len(self._sources)
            line_height = 16.0
            max_rows = max(1, int((self.height() - 8) // line_height))
            show_rows = min(count, max_rows)
            if show_rows < count:
                show_rows = max(1, show_rows - 1)  # одна строка уйдёт под «ещё N»
            font = QFont(self.font())
            font.setPointSize(8 if line_height >= 15 else 7)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            available_width = max(60, int(self.width() - legend_x - 22))
            y = max(4.0, (self.height() - line_height * show_rows) / 2)
            for index, item in enumerate(self._sources[:show_rows]):
                color = QColor(PALETTE[index % len(PALETTE)])
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(QRectF(legend_x, y + line_height / 2 - 4, 8, 8), 2, 2)
                painter.setPen(QPen(_text(), 1))
                share = item["total_rub"] / total * 100
                text = f"{item['source']} — {format_rub(item['total_rub'])} ({share:.0f}%)"
                text = metrics.elidedText(text, Qt.ElideRight, available_width)
                painter.drawText(
                    QRectF(legend_x + 14, y, available_width, line_height),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    text,
                )
                y += line_height
            if show_rows < count:
                painter.setPen(QPen(_muted(), 1))
                painter.drawText(
                    QRectF(legend_x + 14, y, available_width, line_height),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    f"…и ещё {count - show_rows}",
                )
        finally:
            painter.end()


# --------------------------------------------------------------------------- #
# Treemap
# --------------------------------------------------------------------------- #
def _worst_ratio(areas: list[float], side: float) -> float:
    if not areas or side <= 0:
        return float("inf")
    total = sum(areas)
    if total <= 0:
        return float("inf")
    return max(
        side * side * max(areas) / (total * total),
        total * total / (side * side * min(areas)),
    )


def _squarify(areas: list[float], rect: QRectF, output: list[QRectF]) -> None:
    """Классический squarified treemap. areas — в порядке убывания."""
    if not areas:
        return
    if len(areas) == 1 or rect.width() <= 0.5 or rect.height() <= 0.5:
        output.extend([rect] * len(areas))
        return

    side = min(rect.width(), rect.height())
    row = [areas[0]]
    rest = list(areas[1:])
    while rest:
        candidate = row + [rest[0]]
        if _worst_ratio(candidate, side) <= _worst_ratio(row, side):
            row = candidate
            rest.pop(0)
        else:
            break

    row_area = sum(row)
    if rect.width() >= rect.height():
        column_width = row_area / rect.height() if rect.height() else rect.width()
        x = rect.left()
        for area in row:
            height = area / column_width if column_width else 0
            output.append(QRectF(x, rect.top(), column_width, height))
            x += column_width
        _squarify(
            rest,
            QRectF(
                rect.left() + column_width,
                rect.top(),
                max(0.0, rect.width() - column_width),
                rect.height(),
            ),
            output,
        )
    else:
        row_height = row_area / rect.width() if rect.width() else rect.height()
        y = rect.top()
        for area in row:
            width = area / row_height if row_height else 0
            output.append(QRectF(rect.left(), y, width, row_height))
            y += row_height
        _squarify(
            rest,
            QRectF(
                rect.left(),
                rect.top() + row_height,
                rect.width(),
                max(0.0, rect.height() - row_height),
            ),
            output,
        )


class TreemapWidget(ChartWidget):
    """Treemap с порогом, «Прочим», иерархией «источник → день» и кликом по источнику."""

    sourceClicked = Signal(object)  # str (источник) или None (сброс)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(70)
        self._result: TreemapResult | None = None
        self._rects: list[tuple[QRectF, TreemapNode, str]] = []  # rect, node, source-label
        self._hover_index = -1
        self.setMouseTracking(True)

    def set_data(self, result: TreemapResult) -> None:
        self._result = result
        self._recompute()
        self.update()

    def set_filter(self, source: str | None) -> None:
        self._filter = source
        self.update()

    _filter: str | None = None

    # --- геометрия ---
    def _recompute(self) -> None:
        self._rects = []
        if self._result is None or not self._result.nodes:
            return
        inner = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if inner.width() <= 4 or inner.height() <= 4:
            return

        nodes = sorted(self._result.nodes, key=lambda node: node.value, reverse=True)
        values = [max(node.value, 0.001) for node in nodes]
        total = sum(values)
        area = inner.width() * inner.height()
        areas = [value / total * area for value in values]
        rects: list[QRectF] = []
        _squarify(areas, inner, rects)

        for rect, node in zip(rects, nodes):
            self._rects.append((rect, node, node.label))
            if node.children:
                header = 16.0
                children_rect = rect.adjusted(2, header, -2, -2)
                if children_rect.width() > 4 and children_rect.height() > 4:
                    child_values = [max(child.value, 0.001) for child in node.children]
                    child_total = sum(child_values)
                    child_areas = [
                        value / child_total * children_rect.width() * children_rect.height()
                        for value in child_values
                    ]
                    child_rects: list[QRectF] = []
                    _squarify(child_areas, children_rect, child_rects)
                    for child_rect, child in zip(child_rects, node.children):
                        self._rects.append((child_rect, child, node.label))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._recompute()

    # --- отрисовка ---
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = self._begin_paint()
        try:
            if not self._rects:
                self._draw_empty(painter)
                return
            font = QFont(self.font())
            font.setPointSize(8)
            painter.setFont(font)

            node_colors: dict[str, QColor] = {}
            if self._result is not None:
                for index, node in enumerate(self._result.nodes):
                    node_colors[node.label] = (
                        QColor(OTHER_COLOR)
                        if node.is_other
                        else QColor(PALETTE[index % len(PALETTE)])
                    )

            for index, (rect, node, source) in enumerate(self._rects):
                color = node_colors.get(source, QColor(PALETTE[0]))
                if node.children:
                    color = color.darker(115)
                if self._filter and source != self._filter:
                    color = QColor(color)
                    color.setAlpha(90)
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor("#ffffff"), 2 if node.children else 1))
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)

                if index == self._hover_index:
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(QPen(_text(), 2))
                    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)

                self._draw_label(painter, rect, node)
        finally:
            painter.end()

    def _draw_label(self, painter: QPainter, rect: QRectF, node: TreemapNode) -> None:
        if rect.width() < 34 or rect.height() < 16:
            return
        label = node.label
        value = format_rub(node.value)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        font = QFont(self.font())
        font.setPointSize(8)
        font.setBold(not node.children)
        painter.setFont(font)
        if rect.height() >= 34 and rect.width() >= 70:
            painter.drawText(
                rect.adjusted(5, 3, -4, -16),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                label,
            )
            small = QFont(font)
            small.setBold(False)
            small.setPointSize(7)
            painter.setFont(small)
            painter.drawText(
                rect.adjusted(5, 17, -4, -3),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                value,
            )
        else:
            painter.drawText(
                rect.adjusted(4, 1, -3, -1),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                f"{label} · {value}" if rect.height() >= 22 else label,
            )

    # --- мышь ---
    def _node_at(self, position: QPointF) -> tuple[QRectF, TreemapNode, str] | None:
        for rect, node, source in reversed(self._rects):
            if rect.contains(position):
                return rect, node, source
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        found = self._node_at(event.position())
        index = -1
        if found is not None:
            for i, (rect, node, source) in enumerate(self._rects):
                if rect == found[0] and node is found[1]:
                    index = i
                    break
            node = found[1]
            if node.is_other:
                tooltip = f"Прочее\n{format_rub(node.value)} · поступлений: {node.count}"
            else:
                tooltip = f"{node.label}\n{format_rub(node.value)} · поступлений: {node.count}"
            QToolTip.showText(event.globalPosition().toPoint(), tooltip, self)
        else:
            QToolTip.hideText()
        if index != self._hover_index:
            self._hover_index = index
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        found = self._node_at(event.position())
        if found is None:
            self.sourceClicked.emit(None)
            return
        _, node, source = found
        if node.is_other:
            # «Прочее» — это корзина источников, а не реальный источник: клик сбрасывает фильтр.
            self.sourceClicked.emit(None)
            return
        self.sourceClicked.emit(source)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        QToolTip.hideText()
        self.update()
