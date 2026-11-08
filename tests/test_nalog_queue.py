# tests/test_nalog_queue.py — удаление из очереди чеков и поиск по списку.

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models import Income
from services import receipts
from storage.db import (
    delete_from_queue,
    enqueue_receipts,
    init_db,
    list_queue,
    mark_receipt_sent,
    upsert_incomes,
)

UTC = timezone.utc


def make_income(external_id: str = "op-1") -> Income:
    return Income(
        external_id=external_id,
        occurred_at=datetime(2031, 1, 5, 12, 0, 0, tzinfo=UTC),
        amount_kopecks=12_345,
        currency="RUB",
        description="Пополнение",
        category="Переводы",
        source="Тестов Т.",
        group="Переводы",
        raw_json="{}",
        inserted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "queue.db"
    init_db(path)
    upsert_incomes([make_income()], path)
    return path


def test_delete_pending_from_queue(db):
    enqueue_receipts(["op-1"], db)
    queue = list_queue(["pending"], db)
    assert len(queue) == 1
    income_id = int(queue[0]["income_id"])

    assert delete_from_queue(income_id, db) is True
    assert list_queue(["pending"], db) == []


def test_delete_sent_is_not_allowed(db):
    enqueue_receipts(["op-1"], db)
    income_id = int(list_queue(["pending"], db)[0]["income_id"])
    mark_receipt_sent(income_id, "receipt-uuid", "https://example/print", db)

    assert delete_from_queue(income_id, db) is False
    assert len(list_queue(["sent"], db)) == 1


def test_service_remove_from_queue(db):
    enqueue_receipts(["op-1"], db)
    income_id = int(list_queue(["pending"], db)[0]["income_id"])
    assert receipts.remove_from_queue(income_id, db_path=db) is True
    assert receipts.remove_from_queue(income_id, db_path=db) is False


# --------------------------------------------------------------------------- #
# Поиск
# --------------------------------------------------------------------------- #
def _row(**overrides) -> dict:
    row = {
        "source": "Тестов Т.",
        "amount_kopecks": 12_345,
        "occurred_at": "2031-01-05T12:00:00+00:00",
        "sent_at": None,
        "description": "Тестов Т. | Перевод денежных средств",
        "status": "pending",
        "error_message": None,
    }
    row.update(overrides)
    return row


def test_matches_query_by_name_case_insensitive():
    assert receipts.matches_query(_row(), "тестов")
    assert receipts.matches_query(_row(), "ТЕСТОВ")
    assert not receipts.matches_query(_row(), "примерова")


def test_matches_query_by_amount_and_date():
    assert receipts.matches_query(_row(), "123,45")
    assert receipts.matches_query(_row(), "05.01.2031")
    assert not receipts.matches_query(_row(), "999")


def test_matches_query_by_description_status_and_error():
    assert receipts.matches_query(_row(), "перевод денежных")
    assert receipts.matches_query(_row(), "в очереди")
    assert receipts.matches_query(_row(status="error", error_message="boom"), "boom")
    assert not receipts.matches_query(_row(), "boom")


def test_matches_query_empty_returns_all():
    assert receipts.matches_query(_row(), "")
    assert receipts.matches_query(_row(), "   ")


def test_format_dt_msk():
    assert receipts.format_dt("2031-01-05T19:17:52+00:00") == "05.01.2031 22:17"
    assert receipts.format_dt("2031-01-10 04:20:00") == "10.01.2031 07:20"
    assert receipts.format_dt(None) == "—"
