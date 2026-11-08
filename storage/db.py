# storage/db.py — версия 0.0.3
# Локальное хранилище пополнений в SQLite (только stdlib sqlite3, без ORM).

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import BACKUP_DIR, DATA_DIR, DB_BACKUP_KEEP, DB_PATH
from core.models import Income

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS incomes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id    TEXT    NOT NULL UNIQUE,
    occurred_at    TEXT    NOT NULL,
    amount_kopecks INTEGER NOT NULL CHECK(amount_kopecks > 0),
    currency       TEXT    NOT NULL DEFAULT 'RUB',
    description    TEXT,
    category       TEXT,
    source         TEXT,
    group_name     TEXT,
    account_id     TEXT,
    raw_json       TEXT,
    is_hidden      INTEGER NOT NULL DEFAULT 0,
    hidden_at      TEXT,
    inserted_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incomes_occurred_at ON incomes(occurred_at);
CREATE INDEX IF NOT EXISTS idx_incomes_is_hidden   ON incomes(is_hidden);
CREATE INDEX IF NOT EXISTS idx_incomes_source      ON incomes(source);

CREATE TABLE IF NOT EXISTS receipt_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    income_id       INTEGER NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'pending',
    receipt_uuid    TEXT,
    receipt_url     TEXT,
    receipt_name    TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at         TEXT,
    FOREIGN KEY (income_id) REFERENCES incomes(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_receipt_queue_status ON receipt_queue(status);
"""

_INSERT_SQL = """
INSERT INTO incomes (
    external_id, occurred_at, amount_kopecks, currency, description,
    category, source, group_name, account_id, raw_json,
    is_hidden, hidden_at, inserted_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(external_id) DO NOTHING
"""


# --------------------------------------------------------------------------- #
# Подключение и схема
# --------------------------------------------------------------------------- #
def _resolve_path(db_path: str | Path | None) -> Path:
    return Path(db_path) if db_path is not None else DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Открывает соединение с настройками WAL / NORMAL / foreign_keys."""
    path = _resolve_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path | None = None) -> None:
    """Создаёт каталоги и схему БД (идемпотентно)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    path = _resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
    logger.info("БД инициализирована: %s", path)


def _migrate(conn: sqlite3.Connection) -> None:
    """Лёгкие миграции для баз, созданных старыми версиями."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(receipt_queue)")}
    if "receipt_name" not in columns:
        conn.execute("ALTER TABLE receipt_queue ADD COLUMN receipt_name TEXT")
        logger.info("Миграция БД: добавлена колонка receipt_queue.receipt_name")


def backup_db(
    keep: int | None = None,
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
) -> Path | None:
    """Делает резервную копию БД и удаляет старые (хранит последние `keep`).

    Возвращает путь к копии или None, если БД ещё не существует.
    """
    source = _resolve_path(db_path)
    if not source.exists():
        return None

    if keep is None:
        keep = DB_BACKUP_KEEP
    target_dir = Path(backup_dir) if backup_dir is not None else BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = target_dir / f"{source.stem}_{stamp}.db"
    shutil.copy2(source, target)

    if keep and keep > 0:
        backups = sorted(target_dir.glob(f"{source.stem}_*.db"))
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)

    logger.info("Бэкап БД: %s", target)
    return target


# --------------------------------------------------------------------------- #
# Преобразования
# --------------------------------------------------------------------------- #
def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _income_to_params(income: Income) -> tuple:
    return (
        income.external_id,
        _utc_iso(income.occurred_at),
        income.amount_kopecks,
        income.currency,
        income.description,
        income.category,
        income.source,
        income.group,
        income.account_id,
        income.raw_json,
        1 if income.is_hidden else 0,
        _utc_iso(income.hidden_at) if income.hidden_at is not None else None,
        _utc_iso(income.inserted_at),
    )


def _row_to_income(row: sqlite3.Row) -> Income:
    return Income(
        external_id=row["external_id"],
        occurred_at=row["occurred_at"],
        amount_kopecks=row["amount_kopecks"],
        currency=row["currency"],
        description=row["description"] or "",
        category=row["category"],
        source=row["source"] or "Прочее",
        group=row["group_name"],
        account_id=row["account_id"],
        raw_json=row["raw_json"] or "{}",
        is_hidden=bool(row["is_hidden"]),
        hidden_at=row["hidden_at"],
        inserted_at=row["inserted_at"],
    )


# --------------------------------------------------------------------------- #
# Запись
# --------------------------------------------------------------------------- #
def upsert_incomes(incomes: list[Income], db_path: str | Path | None = None) -> dict:
    """Вставляет новые пополнения, пропускает дубликаты по external_id.

    Возвращает {"inserted": N, "skipped": M}.
    """
    conn = get_connection(db_path)
    try:
        before = conn.total_changes
        if incomes:
            conn.executemany(_INSERT_SQL, [_income_to_params(i) for i in incomes])
            conn.commit()
        inserted = conn.total_changes - before
    finally:
        conn.close()

    skipped = len(incomes) - inserted
    logger.info("upsert_incomes: inserted=%d, skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


def set_hidden(
    external_id: str,
    hidden: bool,
    db_path: str | Path | None = None,
) -> None:
    """Скрывает/возвращает пополнение. При скрытии пишет hidden_at (UTC)."""
    conn = get_connection(db_path)
    try:
        if hidden:
            conn.execute(
                "UPDATE incomes SET is_hidden = 1, hidden_at = ? WHERE external_id = ?",
                (_utc_iso(datetime.now(timezone.utc)), external_id),
            )
        else:
            conn.execute(
                "UPDATE incomes SET is_hidden = 0, hidden_at = NULL WHERE external_id = ?",
                (external_id,),
            )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Чтение
# --------------------------------------------------------------------------- #
def list_incomes(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    amount_min_kopecks: int | None = None,
    amount_max_kopecks: int | None = None,
    include_hidden: bool = False,
    db_path: str | Path | None = None,
) -> list[Income]:
    """Возвращает пополнения с опциональными фильтрами по дате и сумме."""
    query = "SELECT * FROM incomes WHERE 1 = 1"
    params: list = []

    if not include_hidden:
        query += " AND is_hidden = 0"
    if date_from is not None:
        query += " AND occurred_at >= ?"
        params.append(_utc_iso(date_from))
    if date_to is not None:
        query += " AND occurred_at <= ?"
        params.append(_utc_iso(date_to))
    if amount_min_kopecks is not None:
        query += " AND amount_kopecks >= ?"
        params.append(amount_min_kopecks)
    if amount_max_kopecks is not None:
        query += " AND amount_kopecks <= ?"
        params.append(amount_max_kopecks)

    query += " ORDER BY occurred_at DESC, id DESC"

    conn = get_connection(db_path)
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [_row_to_income(row) for row in rows]


def get_aggregates(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_hidden: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Агрегаты (считаются в SQL): сумма, количество, средний чек.

    Возвращает {"total_kopecks": int, "count": int, "avg_kopecks": int}.
    """
    query = (
        "SELECT COUNT(*) AS count, "
        "COALESCE(SUM(amount_kopecks), 0) AS total, "
        "COALESCE(AVG(amount_kopecks), 0) AS avg "
        "FROM incomes WHERE 1 = 1"
    )
    params: list = []

    if not include_hidden:
        query += " AND is_hidden = 0"
    if date_from is not None:
        query += " AND occurred_at >= ?"
        params.append(_utc_iso(date_from))
    if date_to is not None:
        query += " AND occurred_at <= ?"
        params.append(_utc_iso(date_to))

    conn = get_connection(db_path)
    try:
        row = conn.execute(query, params).fetchone()
    finally:
        conn.close()

    return {
        "total_kopecks": int(row["total"]),
        "count": int(row["count"]),
        "avg_kopecks": int(round(float(row["avg"]))),
    }


def get_hidden_stats(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    amount_min_kopecks: int | None = None,
    amount_max_kopecks: int | None = None,
    db_path: str | Path | None = None,
) -> dict:
    """Статистика по скрытым: {"count": N, "total_kopecks": S}. Отдельный SQL-запрос."""
    query = (
        "SELECT COUNT(*) AS count, "
        "COALESCE(SUM(amount_kopecks), 0) AS total "
        "FROM incomes WHERE is_hidden = 1"
    )
    params: list = []

    if date_from is not None:
        query += " AND occurred_at >= ?"
        params.append(_utc_iso(date_from))
    if date_to is not None:
        query += " AND occurred_at <= ?"
        params.append(_utc_iso(date_to))
    if amount_min_kopecks is not None:
        query += " AND amount_kopecks >= ?"
        params.append(amount_min_kopecks)
    if amount_max_kopecks is not None:
        query += " AND amount_kopecks <= ?"
        params.append(amount_max_kopecks)

    conn = get_connection(db_path)
    try:
        row = conn.execute(query, params).fetchone()
    finally:
        conn.close()

    return {"count": int(row["count"]), "total_kopecks": int(row["total"])}


# --------------------------------------------------------------------------- #
# Очередь чеков «Мой налог»
# --------------------------------------------------------------------------- #
def enqueue_receipts(
    external_ids: list[str],
    db_path: str | Path | None = None,
) -> tuple[int, int]:
    """Ставит поступления в очередь чеков по external_id.

    Возвращает (inserted, already_in_queue). Дубликаты (income_id UNIQUE) игнорируются.
    """
    if not external_ids:
        return 0, 0

    conn = get_connection(db_path)
    try:
        placeholders = ",".join("?" * len(external_ids))
        ids = [
            int(row["id"])
            for row in conn.execute(
                f"SELECT id FROM incomes WHERE external_id IN ({placeholders})",
                list(external_ids),
            ).fetchall()
        ]
        before = conn.total_changes
        if ids:
            conn.executemany(
                "INSERT OR IGNORE INTO receipt_queue (income_id) VALUES (?)",
                [(income_id,) for income_id in ids],
            )
            conn.commit()
        inserted = conn.total_changes - before
    finally:
        conn.close()

    already = len(ids) - inserted
    logger.info("enqueue_receipts: inserted=%d, already=%d", inserted, already)
    return inserted, already


def list_queue(
    statuses: list[str],
    db_path: str | Path | None = None,
) -> list[dict]:
    """Строки очереди с JOIN к incomes, отсортированы по дате поступления."""
    if not statuses:
        return []

    placeholders = ",".join("?" * len(statuses))
    query = f"""
        SELECT q.id            AS queue_id,
               q.income_id     AS income_id,
               q.status        AS status,
               q.receipt_uuid  AS receipt_uuid,
               q.receipt_url   AS receipt_url,
               q.receipt_name  AS receipt_name,
               q.error_message AS error_message,
               q.created_at    AS created_at,
               q.sent_at       AS sent_at,
               i.external_id   AS external_id,
               i.description   AS description,
               i.source        AS source,
               i.amount_kopecks AS amount_kopecks,
               i.occurred_at   AS occurred_at,
               i.is_hidden     AS is_hidden
        FROM receipt_queue q
        JOIN incomes i ON i.id = q.income_id
        WHERE q.status IN ({placeholders})
        ORDER BY i.occurred_at ASC, i.id ASC
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(query, list(statuses)).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def mark_receipt_sent(
    income_id: int,
    receipt_uuid: str,
    receipt_url: str | None = None,
    receipt_name: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE receipt_queue SET status = 'sent', sent_at = datetime('now'), "
            "receipt_uuid = ?, receipt_url = ?, receipt_name = COALESCE(?, receipt_name), "
            "error_message = NULL "
            "WHERE income_id = ?",
            (receipt_uuid, receipt_url, receipt_name, income_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_receipt_error(
    income_id: int,
    error_message: str,
    db_path: str | Path | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE receipt_queue SET status = 'error', error_message = ? "
            "WHERE income_id = ?",
            (error_message, income_id),
        )
        conn.commit()
    finally:
        conn.close()


def clear_receipt_error(
    income_id: int,
    db_path: str | Path | None = None,
) -> None:
    """Сбрасывает error обратно в pending (для повторной отправки)."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE receipt_queue SET status = 'pending', error_message = NULL "
            "WHERE income_id = ? AND status = 'error'",
            (income_id,),
        )
        conn.commit()
    finally:
        conn.close()


def delete_from_queue(
    income_id: int,
    db_path: str | Path | None = None,
) -> bool:
    """Убирает запись из очереди чеков (только pending/error).

    Отправленные чеки не удаляются. Возвращает True, если запись удалена.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM receipt_queue WHERE income_id = ? AND status IN ('pending', 'error')",
            (income_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_from_queue_many(
    income_ids: list[int],
    db_path: str | Path | None = None,
) -> int:
    """Убирает несколько записей из очереди (pending/error). Возвращает число удалённых."""
    ids = [int(income_id) for income_id in income_ids]
    if not ids:
        return 0
    conn = get_connection(db_path)
    try:
        placeholders = ",".join("?" * len(ids))
        cursor = conn.execute(
            f"DELETE FROM receipt_queue WHERE income_id IN ({placeholders}) "
            "AND status IN ('pending', 'error')",
            ids,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def receipt_statuses(db_path: str | Path | None = None) -> dict[str, str]:
    """Карта external_id -> статус чека ('pending'/'error'/'sent')."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT i.external_id, q.status FROM receipt_queue q "
            "JOIN incomes i ON i.id = q.income_id"
        ).fetchall()
        return {row["external_id"]: row["status"] for row in rows}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CLI-селфтест
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "selftest.db"
        init_db(path)

        incomes = [
            Income(
                external_id=f"selftest-{i}",
                occurred_at=datetime(2026, 1, i, 12, 0, tzinfo=timezone.utc),
                amount_kopecks=i * 10_000,
                currency="RUB",
                description="Селфтест",
                source="Селфтест",
                group="INCOME",
                raw_json="{}",
                inserted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for i in range(1, 4)
        ]

        upserted = upsert_incomes(incomes, path)
        print("upsert:", upserted)

        listed = list_incomes(db_path=path)
        print("list (visible):", [(i.external_id, i.amount_kopecks) for i in listed])
        print("aggregates:", get_aggregates(db_path=path))

        set_hidden("selftest-2", True, path)
        print("after hide selftest-2 -> aggregates:", get_aggregates(db_path=path))

        after = get_aggregates(db_path=path)
        assert upserted == {"inserted": 3, "skipped": 0}, upserted
        assert after == {"total_kopecks": 40_000, "count": 2, "avg_kopecks": 20_000}, after

    print("storage.db selftest OK")
    return 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("usage: python -m storage.db --selftest")
    raise SystemExit(2)
