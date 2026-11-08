# tests/test_csv_loader.py — тесты загрузчика CSV-выписок Т-Банка (без сети).
# ВАЖНО: все данные в тестах синтетические (2031 год, вымышленные имена), не из реальных выписок.

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bank.csv_loader import (
    classify_row,
    extract_source,
    import_csv_to_db,
    load_csv,
    map_row,
)

UTC = timezone.utc

HEADER = [
    "Имя счёта", "Номер карты", "Дата операции", "Сумма операции", "Валюта операции",
    "Сумма в валюте счёта", "Валюта счёта", "Статус", "Категория по-умолчанию",
    "Ваша категория", "MCC", "Описание", "Сообщение", "Округление",
    "Сумма операции с округлением", "Бонусы (включая кэшбэк)", "Учёт в аналитике",
]


def make_row(
    date: str,
    account_amount: str,
    category: str,
    description: str,
    analytics: str = "Да",
    status: str = "Ок",
    message: str = "",
    card: str = "*0000",
) -> dict:
    row = {col: "" for col in HEADER}
    row.update(
        {
            "Имя счёта": "Тест",
            "Номер карты": card,
            "Дата операции": date,
            "Сумма операции": account_amount,
            "Валюта операции": "RUB",
            "Сумма в валюте счёта": account_amount,
            "Валюта счёта": "RUB",
            "Статус": status,
            "Категория по-умолчанию": category,
            "Описание": description,
            "Сообщение": message,
            "Округление": "0,00",
            "Сумма операции с округлением": account_amount,
            "Бонусы (включая кэшбэк)": "0,00",
            "Учёт в аналитике": analytics,
        }
    )
    return row


ROWS = {
    "income": make_row("05.01.2031 22:17:52", "111,11", "Пополнения", "Тестов Т."),
    "transfer": make_row("05.01.2031 21:37:40", "222,22", "Переводы", "Примерова А."),
    "no_analytics": make_row(
        "05.01.2031 21:28:22", "333,33", "Переводы", "Образцова Е.", analytics="Нет"
    ),
    "bonus": make_row("01.01.2031 22:59:13", "999,99", "Бонусы", "Зачисление кэшбэка"),
    "p2p_minsk": make_row(
        "01.01.2031 12:00:00", "1000,00", "Пополнения", "Пополнение. PERSON TO PERSON MINSK BLR"
    ),
    "internal": make_row("01.01.2031 17:30:57", "555,55", "Переводы", "Себе из другого банка"),
    "negative": make_row("01.01.2031 10:00:00", "-111,11", "Переводы", "Пользователь П."),
    "not_ok": make_row(
        "01.01.2031 09:00:00", "666,66", "Переводы", "Тест П.", status="Отменён"
    ),
    "cashback_desc": make_row("01.01.2031 08:00:00", "77,77", "Переводы", "кэшбэк"),
    "message": make_row(
        "04.01.2031 18:13:24", "777,77", "Переводы", "Примерова А.",
        message="Перевод денежных средств",
    ),
}


@pytest.fixture()
def csv_path(tmp_path):
    path = tmp_path / "ops.csv"
    lines = [";".join(HEADER)]
    for row in ROWS.values():
        lines.append(";".join(str(row.get(col, "")) for col in HEADER))
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return path


# --------------------------------------------------------------------------- #
# load_csv
# --------------------------------------------------------------------------- #
def test_load_csv_reads_bom_and_semicolon(csv_path):
    rows = load_csv(csv_path)
    assert len(rows) == len(ROWS)
    assert "Дата операции" in rows[0]  # BOM в имени колонки отсутствует
    assert rows[0]["Описание"] == "Тестов Т."


# --------------------------------------------------------------------------- #
# Парсинг даты (MSK -> UTC) и суммы
# --------------------------------------------------------------------------- #
def test_parse_date_msk_to_utc():
    income = map_row(ROWS["income"])
    assert income is not None
    assert income.occurred_at == datetime(2031, 1, 5, 19, 17, 52, tzinfo=UTC)
    assert income.occurred_at.tzinfo is not None


def test_parse_amount_kopecks():
    assert map_row(ROWS["income"]).amount_kopecks == 11_111
    assert map_row(ROWS["p2p_minsk"]).amount_kopecks == 100_000
    assert map_row(ROWS["bonus"]).amount_kopecks == 99_999


# --------------------------------------------------------------------------- #
# classify_row
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("no_analytics", "not_in_analytics"),
        ("bonus", "bonus"),
        ("internal", "internal"),
        ("negative", "non_positive"),
        ("not_ok", "not_ok"),
        ("cashback_desc", "cashback"),
    ],
)
def test_classify_excluded(key, reason):
    assert classify_row(ROWS[key]) == (True, reason)


@pytest.mark.parametrize("key", ["income", "transfer", "p2p_minsk", "message"])
def test_classify_included(key):
    assert classify_row(ROWS[key]) == (False, None)


# --------------------------------------------------------------------------- #
# extract_source
# --------------------------------------------------------------------------- #
def test_extract_source_person_name():
    assert extract_source(ROWS["income"]) == "Тестов Т."
    assert extract_source(ROWS["transfer"]) == "Примерова А."


def test_extract_source_p2p_minsk():
    assert extract_source(ROWS["p2p_minsk"]) == "Минск P2P"


def test_extract_source_fallback_to_category():
    assert extract_source(ROWS["internal"]) == "Переводы"
    assert extract_source(ROWS["bonus"]) == "Бонусы"


# --------------------------------------------------------------------------- #
# external_id детерминирован
# --------------------------------------------------------------------------- #
def test_external_id_is_deterministic():
    first = map_row(ROWS["income"])
    second = map_row(ROWS["income"])
    assert first.external_id == second.external_id
    assert len(first.external_id) == 16


def test_external_id_changes_with_amount():
    base = map_row(ROWS["income"])
    other = map_row(make_row("05.01.2031 22:17:52", "111,12", "Пополнения", "Тестов Т."))
    assert base.external_id != other.external_id


# --------------------------------------------------------------------------- #
# description с "Сообщение"
# --------------------------------------------------------------------------- #
def test_description_includes_message():
    income = map_row(ROWS["message"])
    assert income.description == "Примерова А. | Перевод денежных средств"


# --------------------------------------------------------------------------- #
# Импорт и идемпотентность
# --------------------------------------------------------------------------- #
def test_import_and_idempotency(csv_path, tmp_path):
    db_path = tmp_path / "test.db"

    first = import_csv_to_db(csv_path, db_path)
    assert first["total"] == len(ROWS)
    assert first["inserted"] == 4  # income, transfer, p2p_minsk, message
    assert first["skipped"] == 0
    assert first["excluded"] == 6
    assert first["excluded_reasons"] == {
        "not_in_analytics": 1,
        "bonus": 1,
        "internal": 1,
        "non_positive": 1,
        "not_ok": 1,
        "cashback": 1,
    }

    second = import_csv_to_db(csv_path, db_path)
    assert second["inserted"] == 0
    assert second["skipped"] == 4

    from storage.db import get_aggregates, list_incomes

    incomes = list_incomes(db_path=db_path)
    assert len(incomes) == 4
    assert get_aggregates(db_path=db_path)["count"] == 4
