# core/summary.py — сводка по чекам, оценка налога НПД и прогресс лимита.

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from core.analytics import MSK
from core.models import Income

RECEIPT_LABELS = {
    "sent": "отправлен",
    "pending": "в очереди",
    "error": "ошибка",
    None: "нет",
}

NPD_LIMIT_RUB = 2_400_000.0  # лимит НПД в год
NPD_RATES = (4.0, 6.0)  # физлица / юрлица и ИП


def receipt_label(status: str | None) -> str:
    return RECEIPT_LABELS.get(status, status or "нет")


def receipt_summary(incomes: list[Income], statuses: dict[str, str]) -> dict:
    """Сколько пополнений с чеком, в очереди и без чека."""
    result = {
        "total_count": 0,
        "total_rub": 0.0,
        "sent_count": 0,
        "sent_rub": 0.0,
        "queued_count": 0,
        "queued_rub": 0.0,
        "none_count": 0,
        "none_rub": 0.0,
    }
    for income in incomes:
        rub = income.amount_kopecks / 100
        result["total_count"] += 1
        result["total_rub"] += rub
        status = statuses.get(income.external_id)
        if status == "sent":
            result["sent_count"] += 1
            result["sent_rub"] += rub
        elif status in ("pending", "error"):
            result["queued_count"] += 1
            result["queued_rub"] += rub
        else:
            result["none_count"] += 1
            result["none_rub"] += rub
    return result


def tax_estimate_rub(total_rub: float, rate_percent: float) -> float:
    """Оценка налога: сумма * ставка, округление до копеек (Decimal)."""
    if total_rub <= 0:
        return 0.0
    rate = Decimal(str(max(0.0, rate_percent))) / Decimal(100)
    amount = Decimal(str(total_rub)) * rate
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def npd_progress(year_total_rub: float, limit_rub: float = NPD_LIMIT_RUB) -> float:
    """Процент использования годового лимита НПД (может быть > 100)."""
    if limit_rub <= 0:
        return 0.0
    return max(0.0, year_total_rub) / limit_rub * 100


def year_total_rub(incomes: list[Income], year: int) -> float:
    """Сумма всех пополнений за календарный год (по МСК).

    Скрытые строки тоже учитываются: они реальные поступления, просто не показаны
    в аналитике. Пополнения считаются по дате операции.
    """
    total = 0
    for income in incomes:
        if income.occurred_at.astimezone(MSK).year == year:
            total += income.amount_kopecks
    return total / 100


def current_year() -> int:
    return datetime.now(tz=timezone.utc).astimezone(MSK).year
