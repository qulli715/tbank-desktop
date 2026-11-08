# tests/test_logging_setup.py — версия 0.0.11
# Тесты настройки логирования (файл с ротацией).

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from core.logging_setup import reset_logging, setup_logging


@pytest.fixture(autouse=True)
def _clean_logging():
    reset_logging()
    yield
    reset_logging()


def _file_handlers() -> int:
    return sum(
        1 for handler in logging.getLogger().handlers if isinstance(handler, RotatingFileHandler)
    )


def test_setup_logging_creates_file_and_writes(tmp_path):
    log_file = tmp_path / "app.log"

    setup_logging(log_file=log_file, level="INFO")
    logging.getLogger("tbank.test").info("привет-лог")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    assert "привет-лог" in log_file.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    log_file = tmp_path / "app.log"

    setup_logging(log_file=log_file)
    first = _file_handlers()
    setup_logging(log_file=log_file)
    second = _file_handlers()

    assert first == 1
    assert second == 1
