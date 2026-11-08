# services/csv_import.py — импорт CSV-выписки, тонкая обёртка над bank.csv_loader.

from __future__ import annotations

from pathlib import Path
from typing import Callable

from bank.csv_loader import import_csv_to_db

ProgressFn = Callable[[str], None]


def import_csv(
    path: str | Path,
    db_path: str | Path | None = None,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Импортирует CSV-выписку и возвращает статистику.

    Результат: total / inserted / skipped / excluded / excluded_reasons.
    """
    if on_progress is not None:
        on_progress(f"Читаю файл: {Path(path).name}")
    return import_csv_to_db(path, db_path)
