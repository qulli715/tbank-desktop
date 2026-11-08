# core/treemap.py — данные для treemap без Qt: порог источников, «Прочее», иерархия.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from core.analytics import MSK
from core.models import Income

METRIC_SUM = "sum"
METRIC_AVG = "avg"
HIERARCHY_SOURCE = "source"
HIERARCHY_SOURCE_DAY = "source_day"


@dataclass(frozen=True)
class TreemapNode:
    label: str
    value: float  # рубли: сумма или средний чек (по метрике)
    count: int
    total_kopecks: int
    is_other: bool = False
    children: tuple["TreemapNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TreemapResult:
    nodes: tuple[TreemapNode, ...]
    shown_sources: int
    other_sources: int
    other_total_rub: float
    total_rub: float
    metric: str
    hierarchy: str
    capped: bool = False  # сработал ли лимит max_sources


DEFAULT_MAX_SOURCES = 30


def _source_value(kopecks: int, count: int, metric: str) -> float:
    if metric == METRIC_AVG:
        return (kopecks / count / 100) if count else 0.0
    return kopecks / 100


def _day_children(
    incomes: list[Income],
    metric: str,
) -> tuple[TreemapNode, ...]:
    """Дни внутри источника (только для метрики «Сумма»)."""
    days: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for income in incomes:
        day = income.occurred_at.astimezone(MSK).date()
        days[day][0] += income.amount_kopecks
        days[day][1] += 1
    return tuple(
        TreemapNode(
            label=day.strftime("%d.%m.%Y"),
            value=kopecks / 100,
            count=count,
            total_kopecks=kopecks,
        )
        for day, (kopecks, count) in sorted(days.items())
    )


def build_treemap(
    incomes: list[Income],
    metric: str = METRIC_SUM,
    hierarchy: str = HIERARCHY_SOURCE,
    threshold_rub: float = 500.0,
    max_sources: int = DEFAULT_MAX_SOURCES,
) -> TreemapResult:
    """Строит узлы treemap: источники по сумме, хвост ниже порога -> «Прочее».

    metric: sum | avg. Для avg иерархия принудительно по источникам.
    max_sources: сколько крупнейших источников показывать (остальные в «Прочее»).
    """
    if metric == METRIC_AVG:
        hierarchy = HIERARCHY_SOURCE

    grouped: dict[str, list[Income]] = defaultdict(list)
    for income in incomes:
        grouped[income.source or "Прочее"].append(income)

    totals: list[tuple[str, int, int]] = []
    for source, items in grouped.items():
        kopecks = sum(item.amount_kopecks for item in items)
        totals.append((source, kopecks, len(items)))
    totals.sort(key=lambda item: item[1], reverse=True)

    threshold_kopecks = max(0, int(round(threshold_rub * 100)))
    shown: list[tuple[str, int, int]] = []
    tail: list[tuple[str, int, int]] = []
    for item in totals:
        if item[1] >= threshold_kopecks:
            shown.append(item)
        else:
            tail.append(item)

    capped = False
    if max_sources > 0 and len(shown) > max_sources:
        tail = shown[max_sources:] + tail
        shown = shown[:max_sources]
        capped = True

    total_kopecks = sum(item[1] for item in totals)

    nodes: list[TreemapNode] = []
    for source, kopecks, count in shown:
        children: tuple[TreemapNode, ...] = ()
        if hierarchy == HIERARCHY_SOURCE_DAY:
            children = _day_children(grouped[source], metric)
        nodes.append(
            TreemapNode(
                label=source,
                value=_source_value(kopecks, count, metric),
                count=count,
                total_kopecks=kopecks,
                children=children,
            )
        )

    other_total = sum(item[1] for item in tail)
    other_count = sum(item[2] for item in tail)
    if tail:
        other_children: tuple[TreemapNode, ...] = ()
        if hierarchy == HIERARCHY_SOURCE_DAY:
            other_incomes = [income for source, _, _ in tail for income in grouped[source]]
            other_children = _day_children(other_incomes, metric)
        nodes.append(
            TreemapNode(
                label="Прочее",
                value=_source_value(other_total, other_count, metric),
                count=other_count,
                total_kopecks=other_total,
                is_other=True,
                children=other_children,
            )
        )

    return TreemapResult(
        nodes=tuple(nodes),
        shown_sources=len(shown),
        other_sources=len(tail),
        other_total_rub=other_total / 100,
        total_rub=total_kopecks / 100,
        metric=metric,
        hierarchy=hierarchy,
        capped=capped,
    )
