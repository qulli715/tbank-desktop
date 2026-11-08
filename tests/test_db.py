# tests/test_db.py — версия 0.0.3
# Тесты SQLite-хранилища на временной БД (без сети, только stdlib sqlite3).

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from core.models import Income
from storage.db import (
    get_aggregates,
    get_connection,
    init_db,
    list_incomes,
    set_hidden,
    upsert_incomes,
)

UTC = timezone.utc


def dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, 0, 0, tzinfo=UTC)


def make_income(
    external_id: str,
    occurred_at: datetime | None = None,
    amount_kopecks: int = 10_000,
    **overrides,
) -> Income:
    kwargs = {
        "external_id": external_id,
        "occurred_at": occurred_at or dt(1),
        "amount_kopecks": amount_kopecks,
        "currency": "RUB",
        "description": "Пополнение",
        "category": None,
        "source": "Тестов Т.",
        "group": "INCOME",
        "account_id": "40817810000023685898",
        "raw_json": "{}",
        "is_hidden": False,
        "hidden_at": None,
        "inserted_at": dt(1, 13),
    }
    kwargs.update(overrides)
    return Income(**kwargs)


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


# --------------------------------------------------------------------------- #
# a) init_db создаёт файл и таблицу
# --------------------------------------------------------------------------- #
def test_init_db_creates_file_and_table(db_path):
    assert db_path.exists()

    conn = get_connection(db_path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='incomes'"
        ).fetchone()
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert table is not None
    assert {"idx_incomes_occurred_at", "idx_incomes_is_hidden", "idx_incomes_source"} <= indexes


# --------------------------------------------------------------------------- #
# b) upsert 3 → inserted=3; повтор тех же → inserted=0, skipped=3
# --------------------------------------------------------------------------- #
def test_upsert_inserts_then_skips(db_path):
    incomes = [make_income(f"op-{i}") for i in range(3)]

    first = upsert_incomes(incomes, db_path)
    assert first == {"inserted": 3, "skipped": 0}

    second = upsert_incomes(incomes, db_path)
    assert second == {"inserted": 0, "skipped": 3}


# --------------------------------------------------------------------------- #
# c) 1 новая + 2 старые → inserted=1, skipped=2
# --------------------------------------------------------------------------- #
def test_upsert_mixed(db_path):
    upsert_incomes([make_income("op-1"), make_income("op-2")], db_path)

    result = upsert_incomes(
        [make_income("op-1"), make_income("op-2"), make_income("op-3")],
        db_path,
    )
    assert result == {"inserted": 1, "skipped": 2}


# --------------------------------------------------------------------------- #
# d) list_incomes без фильтров возвращает все не скрытые
# --------------------------------------------------------------------------- #
def test_list_default_excludes_hidden(db_path):
    upsert_incomes(
        [
            make_income("op-1", occurred_at=dt(1)),
            make_income("op-2", occurred_at=dt(2)),
            make_income("op-3", occurred_at=dt(3), is_hidden=True, hidden_at=dt(3)),
        ],
        db_path,
    )

    ids = {i.external_id for i in list_incomes(db_path=db_path)}
    assert ids == {"op-1", "op-2"}


# --------------------------------------------------------------------------- #
# e) include_hidden=True возвращает все
# --------------------------------------------------------------------------- #
def test_list_include_hidden(db_path):
    upsert_incomes(
        [
            make_income("op-1"),
            make_income("op-2", is_hidden=True, hidden_at=dt(2)),
        ],
        db_path,
    )

    ids = {i.external_id for i in list_incomes(include_hidden=True, db_path=db_path)}
    assert ids == {"op-1", "op-2"}


# --------------------------------------------------------------------------- #
# f) фильтр по датам отсекает крайние
# --------------------------------------------------------------------------- #
def test_list_date_filter(db_path):
    upsert_incomes(
        [
            make_income("op-1", occurred_at=dt(1)),
            make_income("op-2", occurred_at=dt(5)),
            make_income("op-3", occurred_at=dt(10)),
        ],
        db_path,
    )

    result = list_incomes(
        date_from=dt(3),
        date_to=dt(7),
        db_path=db_path,
    )
    assert [i.external_id for i in result] == ["op-2"]


# --------------------------------------------------------------------------- #
# g) фильтр по сумме включительно
# --------------------------------------------------------------------------- #
def test_list_amount_filter_inclusive(db_path):
    upsert_incomes(
        [
            make_income("op-1", amount_kopecks=10_000),
            make_income("op-2", amount_kopecks=20_000),
            make_income("op-3", amount_kopecks=30_000),
        ],
        db_path,
    )

    result = list_incomes(
        amount_min_kopecks=20_000,
        amount_max_kopecks=30_000,
        db_path=db_path,
    )
    assert {i.external_id for i in result} == {"op-2", "op-3"}


# --------------------------------------------------------------------------- #
# h) set_hidden(True) убирает из list_incomes и из агрегатов
# --------------------------------------------------------------------------- #
def test_set_hidden_excludes_from_list_and_aggregates(db_path):
    upsert_incomes(
        [
            make_income("op-1", amount_kopecks=10_000),
            make_income("op-2", amount_kopecks=20_000),
            make_income("op-3", amount_kopecks=30_000),
        ],
        db_path,
    )

    before = get_aggregates(db_path=db_path)
    assert before == {"total_kopecks": 60_000, "count": 3, "avg_kopecks": 20_000}

    set_hidden("op-2", True, db_path)

    ids = {i.external_id for i in list_incomes(db_path=db_path)}
    assert ids == {"op-1", "op-3"}

    after = get_aggregates(db_path=db_path)
    assert after == {"total_kopecks": 40_000, "count": 2, "avg_kopecks": 20_000}

    # hidden_at проставился
    hidden = list_incomes(include_hidden=True, db_path=db_path)
    op2 = next(i for i in hidden if i.external_id == "op-2")
    assert op2.is_hidden is True
    assert op2.hidden_at is not None


# --------------------------------------------------------------------------- #
# i) set_hidden(False) возвращает
# --------------------------------------------------------------------------- #
def test_set_hidden_false_restores(db_path):
    upsert_incomes([make_income("op-1", amount_kopecks=15_000)], db_path)

    set_hidden("op-1", True, db_path)
    assert get_aggregates(db_path=db_path)["count"] == 0

    set_hidden("op-1", False, db_path)
    restored = list_incomes(db_path=db_path)
    assert [i.external_id for i in restored] == ["op-1"]
    assert restored[0].is_hidden is False
    assert restored[0].hidden_at is None
    assert get_aggregates(db_path=db_path) == {
        "total_kopecks": 15_000,
        "count": 1,
        "avg_kopecks": 15_000,
    }


# --------------------------------------------------------------------------- #
# j) get_aggregates на пустой таблице
# --------------------------------------------------------------------------- #
def test_aggregates_empty(db_path):
    assert get_aggregates(db_path=db_path) == {
        "total_kopecks": 0,
        "count": 0,
        "avg_kopecks": 0,
    }


# --------------------------------------------------------------------------- #
# k) CHECK constraint: amount_kopecks = 0 напрямую падает
# --------------------------------------------------------------------------- #
def test_check_constraint_rejects_zero(db_path):
    conn = get_connection(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO incomes (external_id, occurred_at, amount_kopecks, "
                "inserted_at) VALUES (?, ?, ?, ?)",
                ("bad", "2026-01-01T00:00:00+00:00", 0, "2026-01-01T00:00:00+00:00"),
            )
            conn.commit()
    finally:
        conn.close()
