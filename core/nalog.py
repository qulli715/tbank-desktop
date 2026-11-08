# core/nalog.py — версия 0.0.17
# Отправка чеков в ФНС «Мой налог» через moy-nalog-api (ленивый импорт, SMS-вход).

from __future__ import annotations

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional

import config
from storage.db import (
    clear_receipt_error,
    list_queue,
    mark_receipt_error,
    mark_receipt_sent,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str], None]
SLEEP_BETWEEN_RECEIPTS = 0.1  # 100 мс


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# --------------------------------------------------------------------------- #
# Клиент и авторизация (ленивый импорт moy_nalog)
# --------------------------------------------------------------------------- #
def get_nalog_client(session_file: Optional[str] = None):
    """Создаёт синхронный клиент «Мой налог» с сохранённой сессией."""
    from moy_nalog import MoyNalogClientSync

    return MoyNalogClientSync(
        session_file=str(session_file or config.NALOG_SESSION_FILE)
    )


def request_sms(phone: str, session_file: Optional[str] = None):
    """Запрашивает SMS-код. Возвращает challenge (challenge_token, expire_in)."""
    client = get_nalog_client(session_file)
    try:
        return client.request_sms_code(phone)
    finally:
        client.close()


def verify_sms(
    phone: str,
    challenge_token: str,
    code: str,
    session_file: Optional[str] = None,
):
    """Проверяет SMS-код, сохраняет сессию. Возвращает UserProfile."""
    client = get_nalog_client(session_file)
    try:
        return client.auth_by_sms(
            phone=phone,
            challenge_token=challenge_token,
            code=code,
        )
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# Отправка чеков (клиент уже авторизован и передан снаружи)
# --------------------------------------------------------------------------- #
def send_receipts(
    client,
    on_progress: Optional[ProgressFn] = None,
    db_path=None,
    only_failed: bool = False,
    receipt_name: Optional[str] = None,
) -> list[dict]:
    """Создаёт чеки по очереди (pending + error). Ошибка одной записи не рвёт цикл.

    receipt_name — наименование услуги в чеке (по умолчанию из конфига).
    """
    if only_failed:
        for row in list_queue(["error"], db_path=db_path):
            clear_receipt_error(row["income_id"], db_path=db_path)

    name = (receipt_name or "").strip() or config.NALOG_RECEIPT_NAME
    rows = list_queue(["pending", "error"], db_path=db_path)
    results: list[dict] = []
    total = len(rows)

    for index, row in enumerate(rows):
        if index > 0:
            time.sleep(SLEEP_BETWEEN_RECEIPTS)

        income_id = row["income_id"]
        try:
            receipt = client.create_receipt(
                name=name,
                amount=Decimal(row["amount_kopecks"]) / 100,
                operation_time=_parse_datetime(row["occurred_at"]),
            )
            mark_receipt_sent(
                income_id,
                receipt.uuid,
                getattr(receipt, "print_url", None),
                receipt_name=name,
                db_path=db_path,
            )
            results.append({"income_id": income_id, "status": "sent", "error": None})
        except Exception as exc:  # noqa: BLE001 — ошибка одной записи не должна ронять цикл
            logger.exception("Ошибка создания чека для income_id=%s", income_id)
            mark_receipt_error(income_id, str(exc), db_path=db_path)
            results.append({"income_id": income_id, "status": "error", "error": str(exc)})

        if on_progress is not None:
            on_progress(index, total, f"Создаю чек {index + 1} из {total}…")

    logger.info(
        "send_receipts: всего=%d, успешно=%d, ошибок=%d, only_failed=%s",
        len(results),
        sum(1 for r in results if r["status"] == "sent"),
        sum(1 for r in results if r["status"] == "error"),
        only_failed,
    )
    return results


def retry_failed(
    client,
    on_progress: Optional[ProgressFn] = None,
    db_path=None,
    receipt_name: Optional[str] = None,
) -> list[dict]:
    """Повторяет только записи со статусом error."""
    return send_receipts(
        client,
        on_progress=on_progress,
        db_path=db_path,
        only_failed=True,
        receipt_name=receipt_name,
    )
