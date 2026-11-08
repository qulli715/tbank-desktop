# tests/test_backup.py — версия 0.0.11
# Тесты резервного копирования БД.

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core.models import Income
from storage.db import backup_db, init_db, upsert_incomes

UTC = timezone.utc


def _seed(db_path) -> None:
    init_db(db_path)
    upsert_incomes(
        [
            Income(
                external_id="a",
                occurred_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
                amount_kopecks=10_000,
                currency="RUB",
                description="Пополнение",
                source="Тестов Т.",
                raw_json="{}",
                inserted_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        ],
        db_path,
    )


def test_backup_returns_none_when_db_missing(tmp_path):
    assert backup_db(db_path=tmp_path / "nope.db", backup_dir=tmp_path / "b") is None


def test_backup_creates_copy(tmp_path):
    db_path = tmp_path / "tbank.db"
    _seed(db_path)
    backup_dir = tmp_path / "backups"

    result = backup_db(db_path=db_path, backup_dir=backup_dir)

    assert result is not None
    assert result.exists()
    assert result.parent == backup_dir
    assert result.name.startswith("tbank_")
    # копия — корректная SQLite-база с той же записью
    conn = sqlite3.connect(result)
    try:
        count = conn.execute("SELECT COUNT(*) FROM incomes").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_backup_keeps_last_n(tmp_path):
    db_path = tmp_path / "tbank.db"
    _seed(db_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    for i in range(9):
        (backup_dir / f"tbank_2026010{i + 1}_000000.db").write_text("x")

    backup_db(keep=7, db_path=db_path, backup_dir=backup_dir)

    files = sorted(backup_dir.glob("tbank_*.db"))
    assert len(files) == 7
