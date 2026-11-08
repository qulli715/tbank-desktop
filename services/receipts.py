# services/receipts.py — «Мой налог»: сессия, SMS-вход, очередь, отправка чеков.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import config
from core.analytics import format_rub_exact
from core.nalog import (
    get_nalog_client,
    request_sms,
    retry_failed,
    send_receipts,
    verify_sms,
)
from storage.db import (
    delete_from_queue,
    delete_from_queue_many,
    enqueue_receipts,
    list_queue,
    receipt_statuses,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str], None]

QUEUE_STATUSES = ("pending", "error")
STATUS_LABELS = {"pending": "в очереди", "error": "ошибка", "sent": "отправлен"}
_TZ = ZoneInfo(config.DISPLAY_TZ)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def format_dt(value, sqlite: bool = False) -> str:
    """ISO/`YYYY-MM-DD HH:MM:SS` (UTC) -> 'дд.мм.гггг ЧЧ:ММ' в таймзоне отображения."""
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        try:
            moment = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")


def matches_query(row: dict, query: str) -> bool:
    """Поиск по строке чека: имя источника, сумма, даты, описание, статус, ошибка."""
    needle = (query or "").strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        (
            str(row.get("source") or ""),
            str(row.get("description") or ""),
            format_rub_exact(row.get("amount_kopecks", 0) / 100),
            format_dt(row.get("occurred_at")),
            format_dt(row.get("sent_at")),
            status_label(str(row.get("status") or "")),
            str(row.get("error_message") or ""),
        )
    ).lower()
    return needle in haystack


def sms_error_text(exc: Exception) -> str:
    """Человеко-понятный текст ошибки входа/отправки."""
    try:
        from moy_nalog import (
            AuthenticationError,
            InvalidSMSCodeError,
            NetworkError,
            SMSRateLimitError,
            TokenExpiredError,
        )
    except Exception:  # noqa: BLE001
        return f"Ошибка: {exc}"

    if isinstance(exc, InvalidSMSCodeError):
        return "Неверный код из SMS."
    if isinstance(exc, SMSRateLimitError):
        return "Слишком часто. Подождите и попробуйте снова."
    if isinstance(exc, TokenExpiredError):
        return "Сессия истекла — войдите заново по SMS."
    if isinstance(exc, AuthenticationError):
        return f"Ошибка авторизации: {exc}"
    if isinstance(exc, NetworkError):
        return "Нет связи с ФНС. Проверьте интернет/VPN и повторите."
    return f"Ошибка: {exc}"


# --------------------------------------------------------------------------- #
# Очередь
# --------------------------------------------------------------------------- #
def enqueue(external_ids) -> tuple[int, int]:
    """Переносит выбранные поступления в очередь чеков."""
    return enqueue_receipts(list(external_ids))


def remove_from_queue(income_id: int, db_path=None) -> bool:
    """Убирает чек из очереди (только pending/error)."""
    return delete_from_queue(income_id, db_path=db_path)


def remove_many_from_queue(income_ids: list[int], db_path=None) -> int:
    """Убирает несколько чеков из очереди; возвращает число удалённых."""
    return delete_from_queue_many(income_ids, db_path=db_path)


def statuses(db_path=None) -> dict[str, str]:
    """Карта external_id -> статус чека (для сверки в аналитике)."""
    return receipt_statuses(db_path=db_path)


def queue() -> list[dict]:
    return list_queue(list(QUEUE_STATUSES))


def sent() -> list[dict]:
    return list_queue(["sent"])


def queue_totals() -> tuple[int, int]:
    rows = queue()
    return len(rows), sum(row["amount_kopecks"] for row in rows)


# --------------------------------------------------------------------------- #
# Сессия и вход
# --------------------------------------------------------------------------- #
def session_authenticated() -> bool:
    client = get_nalog_client()
    try:
        return bool(client.is_authenticated)
    finally:
        client.close()


def fetch_profile() -> dict:
    """Профиль ФНС (сетевой вызов — вызывать из фонового потока)."""
    client = get_nalog_client()
    try:
        profile = client.get_user_profile()
        return {
            "name": getattr(profile, "display_name", None) or "",
            "inn": getattr(profile, "inn", None) or "",
        }
    finally:
        client.close()


def request_code(phone: str) -> dict:
    challenge = request_sms(phone)
    return {
        "challenge_token": challenge.challenge_token,
        "expire_in": getattr(challenge, "expire_in", None),
    }


def login(phone: str, challenge_token: str, code: str) -> dict:
    profile = verify_sms(phone, challenge_token, code)
    return {
        "name": getattr(profile, "display_name", None) or "",
        "inn": getattr(profile, "inn", None) or "",
    }


def logout() -> None:
    client = get_nalog_client()
    try:
        client.clear_session()
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# Отправка
# --------------------------------------------------------------------------- #
def send(
    only_failed: bool,
    on_progress: ProgressFn | None = None,
    receipt_name: str | None = None,
) -> list[dict]:
    """Отправляет чеки в ФНС. Клиент создаётся внутри вызывающего потока."""
    client = get_nalog_client()
    try:
        if only_failed:
            return retry_failed(client, on_progress=on_progress, receipt_name=receipt_name)
        return send_receipts(client, on_progress=on_progress, receipt_name=receipt_name)
    finally:
        client.close()
