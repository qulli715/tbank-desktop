# core/logging_setup.py — версия 0.0.11
# Настройка логирования: файл с ротацией (1 МБ) + консоль.

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_our_handlers: list[logging.Handler] = []


def setup_logging(
    log_file: str | Path | None = None,
    level: str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> Path:
    """Идемпотентно настраивает root-логгер (файл с ротацией + консоль)."""
    path = Path(log_file) if log_file is not None else config.LOG_FILE
    level = level if level is not None else config.LOG_LEVEL
    max_bytes = max_bytes if max_bytes is not None else config.LOG_MAX_BYTES
    backup_count = backup_count if backup_count is not None else config.LOG_BACKUP_COUNT

    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(FORMAT)

    has_file_handler = any(
        isinstance(handler, RotatingFileHandler) for handler in root.handlers
    )
    if not has_file_handler:
        file_handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        _our_handlers.append(file_handler)

    if not any(type(handler) is logging.StreamHandler for handler in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)
        _our_handlers.append(console_handler)

    logging.getLogger(__name__).debug("Логирование настроено: %s", path)
    return path


def reset_logging() -> None:
    """Убирает только наши хендлеры (для тестов/повторной настройки)."""
    root = logging.getLogger()
    for handler in list(_our_handlers):
        if handler in root.handlers:
            root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass
    _our_handlers.clear()
