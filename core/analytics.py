# core/analytics.py — агрегация пополнений без pandas: фильтры, метрики, группировки.
# Деньги везде в копейках, наружу отдаём рубли (float) для отображения.

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from core.models import Income
from storage.db import get_hidden_stats as db_get_hidden_stats
from storage.db import list_incomes as db_list_incomes

MSK = ZoneInfo("Europe/Moscow")

METRIC_KEYS = ("total_rub", "count", "avg_rub", "min_rub", "max_rub")
DAY_KEYS = ("date", "total_rub", "count")
SOURCE_KEYS = ("source", "total_rub", "count")


def format_rub(value: float) -> str:
    """45684.14 -> '45 684 ₽'; 643.4 -> '643 ₽'."""
    return f"{round(value):,}".replace(",", " ") + " ₽"


def format_rub_exact(value: float) -> str:
    """1234.5 -> '1 234,50 ₽' (для таблицы, с копейками)."""
    rubles = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{rubles} ₽"


# --------------------------------------------------------------------------- #
# Фильтры (SQL, для загрузки из БД)
# --------------------------------------------------------------------------- #
def _to_kopecks(rub: float | None) -> int | None:
    return int(round(rub * 100)) if rub is not None else None


def _date_bound_to_utc(value: date | datetime | None, end: bool) -> datetime | None:
    """date -> границы дня по Москве -> UTC. datetime передаётся как есть."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, time.max if end else time.min)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(timezone.utc)


def get_filtered_incomes(
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    amount_min_rub: float | None = None,
    amount_max_rub: float | None = None,
    include_hidden: bool = False,
    db_path=None,
) -> list[Income]:
    """Пополнения из БД с фильтрами. Скрытые исключены по умолчанию."""
    return db_list_incomes(
        date_from=_date_bound_to_utc(date_from, end=False),
        date_to=_date_bound_to_utc(date_to, end=True),
        amount_min_kopecks=_to_kopecks(amount_min_rub),
        amount_max_kopecks=_to_kopecks(amount_max_rub),
        include_hidden=include_hidden,
        db_path=db_path,
    )


def get_hidden_stats(
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    amount_min_rub: float | None = None,
    amount_max_rub: float | None = None,
    db_path=None,
) -> dict:
    """Статистика скрытых: {"count": N, "total_kopecks": S}."""
    return db_get_hidden_stats(
        date_from=_date_bound_to_utc(date_from, end=False),
        date_to=_date_bound_to_utc(date_to, end=True),
        amount_min_kopecks=_to_kopecks(amount_min_rub),
        amount_max_kopecks=_to_kopecks(amount_max_rub),
        db_path=db_path,
    )


# --------------------------------------------------------------------------- #
# Фильтры в памяти (для быстрой перефильтрации без повторных SQL-запросов)
# --------------------------------------------------------------------------- #
def filter_incomes(
    incomes: list[Income],
    date_from: date | None = None,
    date_to: date | None = None,
    amount_min_rub: float | None = None,
    amount_max_rub: float | None = None,
    include_hidden: bool = True,
    source: str | None = None,
) -> list[Income]:
    """Фильтрует список в памяти: даты по МСК, суммы в рублях, источник."""
    result: list[Income] = []
    min_kopecks = _to_kopecks(amount_min_rub)
    max_kopecks = _to_kopecks(amount_max_rub)
    for income in incomes:
        if not include_hidden and income.is_hidden:
            continue
        if source is not None and income.source != source:
            continue
        day = income.occurred_at.astimezone(MSK).date()
        if date_from is not None and day < date_from:
            continue
        if date_to is not None and day > date_to:
            continue
        if min_kopecks is not None and income.amount_kopecks < min_kopecks:
            continue
        if max_kopecks is not None and income.amount_kopecks > max_kopecks:
            continue
        result.append(income)
    return result


# --------------------------------------------------------------------------- #
# Метрики
# --------------------------------------------------------------------------- #
def compute_metrics(incomes: list[Income]) -> dict:
    """Сумма/количество/средний/мин/макс в рублях. На пустом — нули."""
    if not incomes:
        return {"total_rub": 0.0, "count": 0, "avg_rub": 0.0, "min_rub": 0.0, "max_rub": 0.0}

    amounts = [i.amount_kopecks for i in incomes]
    total = sum(amounts)
    count = len(amounts)
    return {
        "total_rub": total / 100,
        "count": count,
        "avg_rub": total / 100 / count,
        "min_rub": min(amounts) / 100,
        "max_rub": max(amounts) / 100,
    }


# --------------------------------------------------------------------------- #
# Группировки (возвращают список словарей)
# --------------------------------------------------------------------------- #
def group_by_day(incomes: list[Income]) -> list[dict]:
    """Поступления по дням (МСК), пропущенные дни заполняются нулями."""
    if not incomes:
        return []

    days: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for income in incomes:
        day = income.occurred_at.astimezone(MSK).date()
        days[day][0] += income.amount_kopecks
        days[day][1] += 1

    current, last = min(days), max(days)
    result: list[dict] = []
    while current <= last:
        kopecks, count = days.get(current, (0, 0))
        result.append({"date": current, "total_rub": kopecks / 100, "count": count})
        current += timedelta(days=1)
    return result


def group_by_source(incomes: list[Income], top_n: int = 10) -> list[dict]:
    """Источники по сумме (убывание). Хвост объединяется в «Прочее»."""
    if not incomes:
        return []

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for income in incomes:
        totals[income.source][0] += income.amount_kopecks
        totals[income.source][1] += 1

    grouped = [
        {"source": source, "total_rub": kopecks / 100, "count": count}
        for source, (kopecks, count) in totals.items()
    ]
    grouped.sort(key=lambda item: item["total_rub"], reverse=True)

    if len(grouped) > top_n:
        top = grouped[:top_n]
        rest = grouped[top_n:]
        other = {
            "source": "Прочее",
            "total_rub": sum(item["total_rub"] for item in rest),
            "count": sum(item["count"] for item in rest),
        }
        top.append(other)
        top.sort(key=lambda item: item["total_rub"], reverse=True)
        grouped = top
    return grouped


def matches_income_query(income: Income, query: str) -> bool:
    """Поиск по строке таблицы «Переводы»: имя, сумма, дата (МСК), описание, категория."""
    needle = (query or "").strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        (
            income.source or "",
            income.description or "",
            income.category or "",
            format_rub_exact(income.amount_kopecks / 100),
            income.occurred_at.astimezone(MSK).strftime("%d.%m.%Y %H:%M"),
            income.external_id,
        )
    ).lower()
    return needle in haystack
