# tests/test_receipt_name_update.py — имя услуги в чеке и проверка обновлений.

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import config
from core import nalog
from core.models import Income
from storage.db import init_db, list_queue, mark_receipt_sent, upsert_incomes
from ui.update_check import is_newer, normalize_tag

UTC = timezone.utc


class FakeClient:
    def __init__(self) -> None:
        self.names: list[str] = []

    def create_receipt(self, name, amount, operation_time=None, **kwargs):  # noqa: ANN001
        self.names.append(name)
        return SimpleNamespace(uuid=f"uuid-{len(self.names)}", print_url="http://receipt")


def make_income(external_id: str = "n1") -> Income:
    return Income(
        external_id=external_id,
        occurred_at=datetime(2031, 1, 5, 12, tzinfo=UTC),
        amount_kopecks=12_345,
        currency="RUB",
        description="Пополнение",
        category="Переводы",
        source="Тестов Т.",
        group="Переводы",
        raw_json="{}",
        inserted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _prepare_db(tmp_path):
    from storage.db import enqueue_receipts

    path = tmp_path / "name.db"
    init_db(path)
    upsert_incomes([make_income()], path)
    enqueue_receipts(["n1"], path)
    return path


def test_send_uses_custom_receipt_name(tmp_path):
    db = _prepare_db(tmp_path)
    client = FakeClient()
    nalog.send_receipts(client, db_path=db, receipt_name="Разработка")
    assert client.names == ["Разработка"]
    sent = list_queue(["sent"], db)
    assert sent[0]["receipt_name"] == "Разработка"


def test_send_uses_default_name_when_empty(tmp_path):
    db = _prepare_db(tmp_path)
    client = FakeClient()
    nalog.send_receipts(client, db_path=db, receipt_name="   ")
    assert client.names == [config.NALOG_RECEIPT_NAME]


def test_mark_sent_keeps_receipt_name(tmp_path):
    db = _prepare_db(tmp_path)
    income_id = int(list_queue(["pending"], db)[0]["income_id"])
    mark_receipt_sent(income_id, "u", "http://r", receipt_name="Обучение", db_path=db)
    assert list_queue(["sent"], db)[0]["receipt_name"] == "Обучение"


# --------------------------------------------------------------------------- #
# Проверка обновлений
# --------------------------------------------------------------------------- #
def test_normalize_tag():
    assert normalize_tag("v1.2.3") == "1.2.3"
    assert normalize_tag("V2.0") == "2.0"


def test_is_newer():
    assert is_newer("v1.1.0", "1.0.0") is True
    assert is_newer("v1.0.1", "1.0.0") is True
    assert is_newer("v1.0.0", "1.0.0") is False
    assert is_newer("v0.9.9", "1.0.0") is False
    assert is_newer("v1.10.0", "1.9.9") is True
