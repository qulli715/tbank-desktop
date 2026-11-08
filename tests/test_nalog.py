# tests/test_nalog.py — версия 0.0.17
# Тесты модуля «Мой налог»: очередь, отправка (client снаружи), SMS-авторизация.

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import core.nalog as nalog
from core.models import Income
from storage.db import (
    clear_receipt_error,
    enqueue_receipts,
    init_db,
    list_queue,
    mark_receipt_error,
    mark_receipt_sent,
    upsert_incomes,
)

UTC = timezone.utc


def make_income(external_id: str, kopecks: int = 10_000) -> Income:
    return Income(
        external_id=external_id,
        occurred_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        amount_kopecks=kopecks,
        currency="RUB",
        description="Пополнение",
        source="Тестов Т.",
        raw_json="{}",
        inserted_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


class FakeReceipt:
    def __init__(self, amount):
        self.uuid = f"uuid-{amount}"
        self.print_url = f"http://receipt/{amount}"


class FakeClient:
    """Мок MoyNalogClientSync: create_receipt + SMS-авторизация."""

    def __init__(self, fail_on_amounts=(), authenticated=True):
        self.fail_on_amounts = set(fail_on_amounts)
        self.is_authenticated = authenticated
        self.closed = False

    def create_receipt(self, name, amount, operation_time=None):
        if float(amount) in self.fail_on_amounts:
            raise RuntimeError("FNS error")
        return FakeReceipt(amount)

    def request_sms_code(self, phone):
        return SimpleNamespace(challenge_token="tok-123", expire_in=300)

    def auth_by_sms(self, phone, challenge_token, code):
        return SimpleNamespace(display_name="Тестов Т.", inn="123456789012")

    def get_user_profile(self):
        return SimpleNamespace(display_name="Тестов Т.", inn="123456789012")

    def close(self):
        self.closed = True


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "nalog.db"
    init_db(path)
    upsert_incomes(
        [make_income("a", 10_000), make_income("b", 20_000), make_income("c", 30_000)],
        path,
    )
    return path


def _install_fake_module(monkeypatch, factory):
    module = types.ModuleType("moy_nalog")
    module.MoyNalogClientSync = factory
    monkeypatch.setitem(sys.modules, "moy_nalog", module)


# --------------------------------------------------------------------------- #
# Ленивый импорт
# --------------------------------------------------------------------------- #
def test_nalog_does_not_import_moy_nalog_lazily():
    assert "moy_nalog" not in sys.modules


def test_get_nalog_client_uses_session_file(monkeypatch):
    captured = {}

    def factory(session_file=None, **kwargs):
        captured["session_file"] = session_file
        return FakeClient()

    _install_fake_module(monkeypatch, factory)
    nalog.get_nalog_client("/tmp/sess.json")
    assert captured["session_file"] == "/tmp/sess.json"


# --------------------------------------------------------------------------- #
# SMS-авторизация
# --------------------------------------------------------------------------- #
def test_request_sms(monkeypatch):
    client = FakeClient(authenticated=False)
    _install_fake_module(monkeypatch, lambda session_file=None, **kw: client)

    challenge = nalog.request_sms("79001234567")
    assert challenge.challenge_token == "tok-123"
    assert challenge.expire_in == 300
    assert client.closed is True


def test_verify_sms(monkeypatch):
    client = FakeClient(authenticated=False)
    _install_fake_module(monkeypatch, lambda session_file=None, **kw: client)

    profile = nalog.verify_sms("79001234567", "tok-123", "123456")
    assert profile.display_name == "Тестов Т."
    assert profile.inn == "123456789012"
    assert client.closed is True


# --------------------------------------------------------------------------- #
# Очередь
# --------------------------------------------------------------------------- #
def test_enqueue_dedup(db_path):
    assert enqueue_receipts(["a", "b"], db_path=db_path) == (2, 0)
    assert enqueue_receipts(["a", "b", "c"], db_path=db_path) == (1, 2)


def test_enqueue_ignores_unknown_external_ids(db_path):
    assert enqueue_receipts(["nope"], db_path=db_path) == (0, 0)


def test_list_queue_join_and_status_filter(db_path):
    enqueue_receipts(["a", "b"], db_path=db_path)
    rows = list_queue(["pending", "error"], db_path=db_path)
    assert len(rows) == 2
    assert rows[0]["source"] == "Тестов Т."
    assert list_queue(["sent"], db_path=db_path) == []


def test_mark_sent_error_clear(db_path):
    enqueue_receipts(["a", "b"], db_path=db_path)
    rows = {
        r["external_id"]: r["income_id"]
        for r in list_queue(["pending"], db_path=db_path)
    }
    mark_receipt_sent(rows["a"], "uuid-a", "http://receipt/a", db_path=db_path)
    mark_receipt_error(rows["b"], "boom", db_path=db_path)

    sent = list_queue(["sent"], db_path=db_path)
    assert len(sent) == 1
    assert sent[0]["receipt_uuid"] == "uuid-a"
    assert sent[0]["sent_at"]

    errors = list_queue(["error"], db_path=db_path)
    assert len(errors) == 1 and errors[0]["error_message"] == "boom"

    clear_receipt_error(rows["b"], db_path=db_path)
    assert list_queue(["error"], db_path=db_path) == []
    assert len(list_queue(["pending"], db_path=db_path)) == 1


# --------------------------------------------------------------------------- #
# Отправка (client передаётся снаружи, без импорта moy_nalog)
# --------------------------------------------------------------------------- #
def test_send_receipts_success_and_error_continues(db_path):
    enqueue_receipts(["a", "b", "c"], db_path=db_path)  # 100 / 200 / 300 руб.
    client = FakeClient(fail_on_amounts={200.0})

    progress_calls: list[tuple] = []
    results = nalog.send_receipts(
        client,
        on_progress=lambda i, t, s: progress_calls.append((i, t, s)),
        db_path=db_path,
    )

    assert len(results) == 3  # цикл не остановился
    assert sum(1 for r in results if r["status"] == "sent") == 2
    assert sum(1 for r in results if r["status"] == "error") == 1
    assert len(progress_calls) == 3
    assert progress_calls[-1][1] == 3

    assert len(list_queue(["sent"], db_path=db_path)) == 2
    errors = list_queue(["error"], db_path=db_path)
    assert len(errors) == 1 and errors[0]["error_message"] == "FNS error"


def test_retry_failed_resends_errors(db_path):
    enqueue_receipts(["a"], db_path=db_path)

    first = nalog.send_receipts(FakeClient(fail_on_amounts={100.0}), db_path=db_path)
    assert first[0]["status"] == "error"
    assert len(list_queue(["error"], db_path=db_path)) == 1

    second = nalog.retry_failed(FakeClient(), db_path=db_path)
    assert second[0]["status"] == "sent"
    assert list_queue(["error"], db_path=db_path) == []
    assert len(list_queue(["sent"], db_path=db_path)) == 1
