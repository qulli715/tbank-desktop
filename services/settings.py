# services/settings.py — настройки приложения (data/settings.json).

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)

THEMES = ("system", "light", "dark")
DEFAULT_RECEIPT_NAME = "Консультационные услуги"
DEFAULT_PRESETS = [DEFAULT_RECEIPT_NAME, "Разработка", "Обучение", "Консультация"]
TAX_RATE_MIN = 0.0
TAX_RATE_MAX = 100.0


@dataclass
class Settings:
    """Пользовательские настройки. Хранятся в data/settings.json (не в git)."""

    theme: str = "system"
    show_line_chart: bool = True
    show_pie_chart: bool = True
    show_treemap: bool = True
    receipt_name: str = DEFAULT_RECEIPT_NAME
    receipt_name_presets: list[str] = field(default_factory=lambda: list(DEFAULT_PRESETS))
    tax_rate: float = 6.0
    confirm_before_send: bool = True


def settings_path() -> Path:
    return config.DATA_DIR / "settings.json"


def _clean_presets(values) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result or list(DEFAULT_PRESETS)


def _clamp_rate(value) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = 6.0
    if rate != rate:  # NaN
        rate = 6.0
    return min(TAX_RATE_MAX, max(TAX_RATE_MIN, rate))


def normalize(settings: Settings) -> Settings:
    """Приводит настройки к допустимым значениям."""
    settings.theme = settings.theme if settings.theme in THEMES else "system"
    settings.receipt_name = (settings.receipt_name or "").strip() or DEFAULT_RECEIPT_NAME
    settings.receipt_name_presets = _clean_presets(settings.receipt_name_presets)
    if settings.receipt_name not in settings.receipt_name_presets:
        settings.receipt_name_presets.insert(0, settings.receipt_name)
    settings.tax_rate = _clamp_rate(settings.tax_rate)
    return settings


def load_settings(path: Path | str | None = None) -> Settings:
    """Читает настройки; при отсутствии/ошибке возвращает значения по умолчанию."""
    target = Path(path) if path is not None else settings_path()
    if not target.exists():
        return Settings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Не удалось прочитать настройки %s: %s", target, exc)
        return Settings()

    settings = Settings()
    for name in asdict(settings):
        if name in raw:
            setattr(settings, name, raw[name])
    return normalize(settings)


def save_settings(settings: Settings, path: Path | str | None = None) -> Path:
    target = Path(path) if path is not None else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    normalize(settings)
    target.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Настройки сохранены: %s", target)
    return target
