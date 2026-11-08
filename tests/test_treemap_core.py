# tests/test_treemap_core.py — данные treemap: порог, «Прочее», иерархия, метрики.

from __future__ import annotations

from datetime import datetime, timezone

from core.models import Income
from core.treemap import (
    HIERARCHY_SOURCE,
    HIERARCHY_SOURCE_DAY,
    METRIC_AVG,
    METRIC_SUM,
    build_treemap,
)

UTC = timezone.utc


def make_income(
    external_id: str,
    amount_kopecks: int,
    source: str,
    day: int = 1,
) -> Income:
    return Income(
        external_id=external_id,
        occurred_at=datetime(2026, 10, day, 12, tzinfo=UTC),
        amount_kopecks=amount_kopecks,
        currency="RUB",
        description="Пополнение",
        category="Переводы",
        source=source,
        group="Переводы",
        raw_json="{}",
        inserted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_empty():
    result = build_treemap([])
    assert result.nodes == ()
    assert result.shown_sources == 0
    assert result.other_sources == 0
    assert result.total_rub == 0.0


def test_threshold_collapses_tail_into_other():
    incomes = [
        make_income("a", 100_000, "Крупный"),  # 1000 ₽
        make_income("b", 60_000, "Средний"),  # 600 ₽
        make_income("c", 40_000, "Мелкий"),  # 400 ₽
        make_income("d", 30_000, "Совсем мелкий"),  # 300 ₽
    ]
    result = build_treemap(incomes, threshold_rub=500)
    labels = [node.label for node in result.nodes]
    assert labels == ["Крупный", "Средний", "Прочее"]
    assert result.shown_sources == 2
    assert result.other_sources == 2
    assert result.other_total_rub == 700.0
    other = result.nodes[-1]
    assert other.is_other is True
    assert other.value == 700.0
    assert other.count == 2
    assert other.total_kopecks == 70_000


def test_all_below_threshold_gives_only_other():
    incomes = [make_income("a", 10_000, "A"), make_income("b", 20_000, "B")]
    result = build_treemap(incomes, threshold_rub=500)
    assert result.shown_sources == 0
    assert result.other_sources == 2
    assert [node.label for node in result.nodes] == ["Прочее"]
    assert result.nodes[0].value == 300.0


def test_average_metric_uses_average_per_source():
    incomes = [
        make_income("a1", 10_000, "A"),  # 100 ₽
        make_income("a2", 30_000, "A"),  # 300 ₽
        make_income("b1", 20_000, "B"),  # 200 ₽
    ]
    result = build_treemap(incomes, metric=METRIC_AVG, threshold_rub=0)
    assert result.metric == METRIC_AVG
    by_label = {node.label: node for node in result.nodes}
    assert by_label["A"].value == 200.0  # средний чек A
    assert by_label["B"].value == 200.0
    assert by_label["A"].count == 2
    assert by_label["A"].total_kopecks == 40_000


def test_source_day_hierarchy_children():
    incomes = [
        make_income("a1", 10_000, "A", day=1),
        make_income("a2", 20_000, "A", day=2),
        make_income("a3", 5_000, "A", day=2),
    ]
    result = build_treemap(
        incomes, metric=METRIC_SUM, hierarchy=HIERARCHY_SOURCE_DAY, threshold_rub=0
    )
    assert result.hierarchy == HIERARCHY_SOURCE_DAY
    node = result.nodes[0]
    assert node.label == "A"
    assert len(node.children) == 2
    assert node.children[0].label == "01.10.2026"
    assert node.children[0].value == 100.0
    assert node.children[1].value == 250.0  # 200 + 50
    assert sum(child.count for child in node.children) == node.count


def test_avg_metric_forces_flat_hierarchy():
    incomes = [make_income("a", 10_000, "A", day=1), make_income("b", 10_000, "A", day=2)]
    result = build_treemap(
        incomes, metric=METRIC_AVG, hierarchy=HIERARCHY_SOURCE_DAY, threshold_rub=0
    )
    assert result.hierarchy == HIERARCHY_SOURCE
    assert result.nodes[0].children == ()


def test_total_rub_uses_all_incomes():
    incomes = [make_income("a", 10_000, "A"), make_income("b", 20_000, "B")]
    result = build_treemap(incomes, threshold_rub=0)
    assert result.total_rub == 300.0
    assert sum(node.value for node in result.nodes) == 300.0


def test_max_sources_cap_moves_rest_to_other():
    incomes = [make_income(f"s{i}", 1_000_00, f"источник {i}") for i in range(35)]
    result = build_treemap(incomes, threshold_rub=0, max_sources=30)
    assert result.capped is True
    assert result.shown_sources == 30
    assert result.other_sources == 5
    assert result.nodes[-1].label == "Прочее"
    assert result.nodes[-1].total_kopecks == 5 * 1_000_00
    assert len(result.nodes) == 31
