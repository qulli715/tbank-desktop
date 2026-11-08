# bank/csv_loader.py — загрузка пополнений из CSV-выписки Т-Банка (без pandas).
# Логика фильтрации, источника и external_id совместима с исходным приложением.

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config
from core.logging_setup import setup_logging
from core.models import Income
from storage.db import init_db, upsert_incomes

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
DATE_FORMAT = "%d.%m.%Y %H:%M:%S"
P2P_MINSK = "Пополнение. PERSON TO PERSON MINSK BLR"
NAME_RE = re.compile(r"^[A-Za-zА-ЯЁа-яё]+(?:\s+[А-ЯЁA-Z]\.)?$")


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def _s(value: Any) -> str:
    """Значение -> строка без пробелов по краям; None -> ""."""
    if value is None:
        return ""
    return str(value).strip()


def load_csv(path: Path | str) -> list[dict]:
    """Читает CSV-выписку Т-Банка (UTF-8 BOM, разделитель ';') в список словарей."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        rows = []
        for raw in reader:
            rows.append({_s(key): _s(value) for key, value in raw.items() if key is not None})
    return rows


def _parse_amount_kopecks(value: Any) -> int:
    """'400,00' -> 40000; поддерживает пробелы, NBSP и минус."""
    raw = _s(value).replace("\xa0", "").replace(" ", "")
    if not raw:
        return 0
    negative = raw.startswith("-")
    raw = raw.lstrip("-").replace(",", ".")
    kopecks = int(round(float(raw) * 100))
    return -kopecks if negative else kopecks


def _parse_msk_datetime(value: Any) -> datetime:
    """'01.01.2031 12:00:00' (MSK) -> tz-aware UTC."""
    dt = datetime.strptime(_s(value), DATE_FORMAT)
    return dt.replace(tzinfo=MSK).astimezone(timezone.utc)


def _description(row: dict) -> str:
    desc = _s(row.get("Описание"))
    message = _s(row.get("Сообщение"))
    return f"{desc} | {message}" if message else desc


# --------------------------------------------------------------------------- #
# Классификация и источник
# --------------------------------------------------------------------------- #
def classify_row(row: dict) -> tuple[bool, str | None]:
    """(excluded, reason) для строки CSV. Порядок правил фиксирован."""
    if _s(row.get("Статус")) != "Ок":
        return True, "not_ok"
    if _s(row.get("Учёт в аналитике")) == "Нет":
        return True, "not_in_analytics"
    if _s(row.get("Категория по-умолчанию")) == "Бонусы":
        return True, "bonus"

    description = _s(row.get("Описание")).lower()
    if "кэшбэк" in description:
        return True, "cashback"
    if "себе из другого банка" in description:
        return True, "internal"
    if _parse_amount_kopecks(row.get("Сумма в валюте счёта")) <= 0:
        return True, "non_positive"
    return False, None


def _looks_like_person_name(value: str) -> bool:
    text = value.strip()
    if not text or len(text) >= 50:
        return False
    low = text.lower()
    if "пополнение" in low or "person to person" in low:
        return False
    return bool(NAME_RE.match(text))


def extract_source(row: dict) -> str:
    """Источник для графиков (в основном — имя отправителя)."""
    category = _s(row.get("Категория по-умолчанию"))
    description = _s(row.get("Описание"))

    if description == P2P_MINSK:
        return "Минск P2P"
    if _looks_like_person_name(description):
        return description
    if category == "Пополнения" and description:
        return description
    return category or "Прочее"


# --------------------------------------------------------------------------- #
# Маппинг в доменную модель
# --------------------------------------------------------------------------- #
def map_row(row: dict) -> Income | None:
    """Преобразует строку CSV в Income."""
    occurred_at = _parse_msk_datetime(row.get("Дата операции"))
    amount_kopecks = _parse_amount_kopecks(row.get("Сумма в валюте счёта"))
    description = _description(row)
    category = _s(row.get("Категория по-умолчанию")) or None

    basis = f"{occurred_at.isoformat()}|{amount_kopecks}|{description}"
    external_id = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    return Income(
        external_id=external_id,
        occurred_at=occurred_at,
        amount_kopecks=amount_kopecks,
        currency=_s(row.get("Валюта счёта")) or config.BASE_CURRENCY,
        description=description,
        category=category,
        source=extract_source(row),
        group=category,
        account_id=None,
        raw_json=json.dumps(row, ensure_ascii=False, default=str),
        inserted_at=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Импорт в БД
# --------------------------------------------------------------------------- #
def import_csv_to_db(path: Path | str, db_path: Path | str | None = None) -> dict:
    """Читает CSV, фильтрует и делает upsert пополнений в SQLite."""
    rows = load_csv(path)

    reasons: Counter = Counter()
    incomes: list[Income] = []
    for row in rows:
        excluded, reason = classify_row(row)
        if excluded:
            reasons[reason] += 1
            continue
        income = map_row(row)
        if income is not None:
            incomes.append(income)

    init_db(db_path)
    upserted = upsert_incomes(incomes, db_path)

    result = {
        "total": len(rows),
        "inserted": upserted["inserted"],
        "skipped": upserted["skipped"],
        "excluded": sum(reasons.values()),
        "excluded_reasons": dict(reasons),
    }
    logger.info("Импорт CSV: %s", result)
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bank.csv_loader")
    parser.add_argument("--file", required=True, help="Путь к CSV-выписке Т-Банка")
    args = parser.parse_args(argv)

    setup_logging()

    path = Path(args.file)
    if not path.exists():
        print(f"Файл не найден: {path}")
        return 1

    stats = import_csv_to_db(path)

    print(f"Файл: {path}")
    print(f"Всего строк: {stats['total']}")
    print(f"Импортировано (новых): {stats['inserted']}")
    print(f"Пропущено (дубликаты): {stats['skipped']}")
    print(f"Исключено: {stats['excluded']}")
    for reason, count in sorted(stats["excluded_reasons"].items()):
        print(f"  - {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
