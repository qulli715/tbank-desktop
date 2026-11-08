# tests/test_receipts_service.py — «Мой налог»: подписи статусов и текст ошибок.
# moy_nalog импортируется лениво (внутри тестов): есть тест, что core.nalog его не тянет.

from __future__ import annotations

from services import receipts


def _exceptions():
    from moy_nalog import (
        AuthenticationError,
        InvalidSMSCodeError,
        NetworkError,
        SMSRateLimitError,
        TokenExpiredError,
    )

    return {
        "invalid_code": InvalidSMSCodeError("bad code"),
        "rate": SMSRateLimitError("rate"),
        "expired": TokenExpiredError("expired"),
        "auth": AuthenticationError("auth"),
        "network": NetworkError("network"),
    }


def test_status_labels():
    assert receipts.status_label("pending") == "в очереди"
    assert receipts.status_label("error") == "ошибка"
    assert receipts.status_label("sent") == "отправлен"
    assert receipts.status_label("unknown") == "unknown"


def test_sms_error_text_mapping():
    errors = _exceptions()
    assert "Неверный код" in receipts.sms_error_text(errors["invalid_code"])
    assert "Слишком часто" in receipts.sms_error_text(errors["rate"])
    assert "Сессия истекла" in receipts.sms_error_text(errors["expired"])
    assert "авторизации" in receipts.sms_error_text(errors["auth"])
    assert "Нет связи" in receipts.sms_error_text(errors["network"])


def test_sms_error_text_generic():
    assert "Ошибка:" in receipts.sms_error_text(ValueError("boom"))


def test_queue_totals(monkeypatch):
    monkeypatch.setattr(
        receipts,
        "queue",
        lambda: [{"amount_kopecks": 100}, {"amount_kopecks": 250}],
    )
    assert receipts.queue_totals() == (2, 350)
