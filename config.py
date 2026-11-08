# config.py — центральный конфиг десктоп-версии (PySide6).
# Портативная сборка: BASE_DIR = папка .exe, данные — в data/ рядом с ней.

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

APP_VERSION = "1.0.0"

if getattr(sys, "frozen", False):  # PyInstaller
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / os.getenv("DB_FILENAME", "tbank.db")
LOG_FILE = DATA_DIR / "app.log"

# --- Таймзона отображения (в БД всегда UTC ISO8601) ---
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "Europe/Moscow")

# --- Логирование ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3

# --- Бэкапы БД ---
DB_BACKUP_KEEP = 7

# --- Валюта ---
BASE_CURRENCY = "RUB"

# --- «Мой налог» (ФНС), неофициальный API ---
NALOG_RECEIPT_NAME = "Консультационные услуги"
NALOG_PHONE: str = os.getenv("NALOG_PHONE", "")
NALOG_SESSION_FILE = DATA_DIR / ".moy-nalog-session.json"
