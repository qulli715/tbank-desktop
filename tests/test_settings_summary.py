# tests/test_settings_summary.py — настройки, сводка по чекам и оценка налога НПД.

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.models import Income
from core.summary import (
    NPD_LIMIT_RUB,
    npd_progress,
    receipt_label,
    receipt_summary,
    tax_estimate_rub,
    year_total_rub,
)
from services import settings as settings_service

UTC = timezone.utc


def make_income(external_id: str, amount_kopecks: int, source: str = "Тестов Т.",
                is_hidden: bool = False, year: int = 2031) -> Income:
    return Income(
        external_id=external_id,
        occurred_at=datetime(year, 1, 5, 12, tzinfo=UTC),
        amount_kopecks=amount_kopecks,
        currency="RUB",
        description="Пополнение",
        category="Переводы",
        source=source,
        group="Переводы",
        raw_json="{}",
        is_hidden=is_hidden,
        inserted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# --------------------------------------------------------------------------- #
# Настройки
# --------------------------------------------------------------------------- #
def test_settings_defaults(tmp_path):
    path = tmp_path / "settings.json"
    settings = settings_service.load_settings(path)
    assert settings.theme == "system"
    assert settings.tax_rate == 6.0
    assert settings.show_line_chart is True
    assert settings.receipt_name


def test_settings_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    settings = settings_service.Settings(
        theme="dark",
        show_pie_chart=False,
        receipt_name="Разработка",
        tax_rate=3.4556435345,
    )
    settings_service.save_settings(settings, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["tax_rate"] == 3.4556435345

    loaded = settings_service.load_settings(path)
    assert loaded.theme == "dark"
    assert loaded.show_pie_chart is False
    assert loaded.receipt_name == "Разработка"
    assert loaded.tax_rate == 3.4556435345


def test_settings_validation(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "theme": "неведомая",
                "tax_rate": 250,
                "receipt_name": "   ",
                "receipt_name_presets": ["", "Обучение", "Обучение"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = settings_service.load_settings(path)
    assert settings.theme == "system"
    assert settings.tax_rate == 100.0
    assert settings.receipt_name == settings_service.DEFAULT_RECEIPT_NAME
    assert settings.receipt_name_presets[0] == settings_service.DEFAULT_RECEIPT_NAME
    assert "Обучение" in settings.receipt_name_presets

    settings.tax_rate = -5
    settings_service.normalize(settings)
    assert settings.tax_rate == 0.0


def test_settings_broken_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{битый json", encoding="utf-8")
    settings = settings_service.load_settings(path)
    assert settings.tax_rate == 6.0


# --------------------------------------------------------------------------- #
# Сводка по чекам
# --------------------------------------------------------------------------- #
def test_receipt_summary_counts():
    incomes = [
        make_income("a", 10_000),
        make_income("b", 20_000),
        make_income("c", 30_000),
    ]
    summary = receipt_summary(incomes, {"a": "sent", "b": "pending"})
    assert summary["total_count"] == 3
    assert summary["total_rub"] == 600.0
    assert summary["sent_count"] == 1 and summary["sent_rub"] == 100.0
    assert summary["queued_count"] == 1 and summary["queued_rub"] == 200.0
    assert summary["none_count"] == 1 and summary["none_rub"] == 300.0


def test_receipt_label():
    assert receipt_label("sent") == "отправлен"
    assert receipt_label("pending") == "в очереди"
    assert receipt_label("error") == "ошибка"
    assert receipt_label(None) == "нет"


# --------------------------------------------------------------------------- #
# Налог и лимит
# --------------------------------------------------------------------------- #
def test_tax_estimate_rounding():
    assert tax_estimate_rub(1000.0, 6) == 60.0
    assert tax_estimate_rub(1000.0, 4) == 40.0
    assert tax_estimate_rub(1234.56, 3.4556435345) == 42.66
    assert tax_estimate_rub(0, 6) == 0.0


def test_npd_progress():
    assert npd_progress(1_200_000) == 50.0
    assert npd_progress(NPD_LIMIT_RUB) == 100.0
    assert npd_progress(NPD_LIMIT_RUB * 1.5) == 150.0
    assert npd_progress(0) == 0.0


def test_year_total_includes_hidden():
    incomes = [
        make_income("a", 10_000),
        make_income("b", 20_000, is_hidden=True),
        make_income("c", 30_000, year=2032),
    ]
    assert year_total_rub(incomes, 2031) == 300.0
