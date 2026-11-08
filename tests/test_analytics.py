# tests/test_analytics.py — тесты агрегации (метрики, группировки, фильтры).

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core.analytics import (
    compute_metrics,
    filter_incomes,
    format_rub,
    format_rub_exact,
    get_filtered_incomes,
    group_by_day,
    group_by_source,
    matches_income_query,
)
from core.models import Income
from storage.db import init_db, upsert_incomes

UTC = timezone.utc


def make_income(
    external_id: str,
    occurred_at: datetime,
    amount_kopecks: int,
    source: str = "Тестов Т.",
    is_hidden: bool = False,
) -> Income:
    return Income(
        external_id=external_id,
        occurred_at=occurred_at,
        amount_kopecks=amount_kopecks,
        currency="RUB",
        description="Пополнение",
        category="Переводы",
        source=source,
        group="Переводы",
        raw_json="{}",
        is_hidden=is_hidden,
        inserted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# compute_metrics / format_rub
# --------------------------------------------------------------------------- #
def test_compute_metrics_three_records():
    incomes = [
        make_income("a", dt(1), 10_000),
        make_income("b", dt(2), 20_000),
        make_income("c", dt(3), 30_000),
    ]
    assert compute_metrics(incomes) == {
        "total_rub": 600.0,
        "count": 3,
        "avg_rub": 200.0,
        "min_rub": 100.0,
        "max_rub": 300.0,
    }


def test_compute_metrics_empty():
    assert compute_metrics([]) == {
        "total_rub": 0.0,
        "count": 0,
        "avg_rub": 0.0,
        "min_rub": 0.0,
        "max_rub": 0.0,
    }


def test_format_rub():
    assert format_rub(45684.14) == "45 684 ₽"
    assert format_rub(643.4) == "643 ₽"


def test_format_rub_exact():
    assert format_rub_exact(1234.5) == "1 234,50 ₽"
    assert format_rub_exact(100) == "100,00 ₽"


# --------------------------------------------------------------------------- #
# group_by_day
# --------------------------------------------------------------------------- #
def test_group_by_day_fills_missing():
    incomes = [make_income("a", dt(1), 10_000), make_income("b", dt(3), 30_000)]
    rows = group_by_day(incomes)
    assert len(rows) == 3  # 1, 2, 3 число
    assert [row["date"].day for row in rows] == [1, 2, 3]
    assert [row["total_rub"] for row in rows] == [100.0, 0.0, 300.0]
    assert [row["count"] for row in rows] == [1, 0, 1]


def test_group_by_day_empty():
    assert group_by_day([]) == []


# --------------------------------------------------------------------------- #
# group_by_source
# --------------------------------------------------------------------------- #
def test_group_by_source_top_n_and_other():
    incomes = [
        make_income(f"p{i}", dt(1), (12 - i) * 10_000, source=f"src{i}")
        for i in range(12)
    ]
    rows = group_by_source(incomes, top_n=10)
    assert len(rows) == 11  # top-10 + «Прочее»
    assert rows[0]["source"] == "src0"  # самая крупная
    assert "Прочее" in {row["source"] for row in rows}
    other = next(row for row in rows if row["source"] == "Прочее")
    assert other["count"] == 2  # src10, src11 объединены


def test_group_by_source_empty():
    assert group_by_source([]) == []


# --------------------------------------------------------------------------- #
# get_filtered_incomes (SQL)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "analytics.db"
    init_db(path)
    upsert_incomes(
        [
            make_income("a", dt(1), 10_000),
            make_income("b", dt(5), 20_000),
            make_income("c", dt(5), 30_000, is_hidden=True),
        ],
        path,
    )
    return path


def test_get_filtered_by_date(db_path):
    result = get_filtered_incomes(
        date_from=date(2026, 10, 3), date_to=date(2026, 10, 6), db_path=db_path
    )
    assert {i.external_id for i in result} == {"b"}


def test_get_filtered_by_amount(db_path):
    result = get_filtered_incomes(
        amount_min_rub=150, amount_max_rub=250, db_path=db_path
    )
    assert {i.external_id for i in result} == {"b"}


def test_get_filtered_hidden_toggle(db_path):
    visible = get_filtered_incomes(db_path=db_path)
    assert {i.external_id for i in visible} == {"a", "b"}

    all_incomes = get_filtered_incomes(include_hidden=True, db_path=db_path)
    assert {i.external_id for i in all_incomes} == {"a", "b", "c"}


# --------------------------------------------------------------------------- #
# filter_incomes (в памяти)
# --------------------------------------------------------------------------- #
def test_filter_incomes_by_date_amount_source_and_hidden():
    incomes = [
        make_income("a", dt(1), 10_000, source="A"),
        make_income("b", dt(3), 20_000, source="B", is_hidden=True),
    ]
    by_date = filter_incomes(incomes, date_from=date(2026, 10, 2), date_to=date(2026, 10, 4))
    assert [i.external_id for i in by_date] == ["b"]

    no_hidden = filter_incomes(incomes, include_hidden=False)
    assert [i.external_id for i in no_hidden] == ["a"]

    by_amount = filter_incomes(incomes, amount_min_rub=150)
    assert [i.external_id for i in by_amount] == ["b"]

    by_source = filter_incomes(incomes, source="A")
    assert [i.external_id for i in by_source] == ["a"]


# --------------------------------------------------------------------------- #
# matches_income_query (поиск по таблице)
# --------------------------------------------------------------------------- #
def test_matches_income_query_by_name_amount_date_category():
    income = make_income("q1", dt(5, 12), 12_345, source="Тестов Т.")
    assert matches_income_query(income, "тестов")
    assert matches_income_query(income, "ТЕСТОВ")
    assert matches_income_query(income, "123,45")
    assert matches_income_query(income, "05.10.2026")
    assert matches_income_query(income, "переводы")  # категория
    assert not matches_income_query(income, "примерова")


def test_matches_income_query_empty_returns_all():
    income = make_income("q2", dt(1), 10_000)
    assert matches_income_query(income, "")
    assert matches_income_query(income, "   ")
