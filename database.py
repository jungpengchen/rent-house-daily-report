"""
SQLite persistence layer.
Tracks seen listings so the daily report only includes new ones.
"""

import sqlite3
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """Create tables if they don't exist."""
    with _connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id          TEXT PRIMARY KEY,   -- "source:source_id"
                source      TEXT NOT NULL,
                source_id   TEXT NOT NULL,
                first_seen  TEXT NOT NULL,       -- ISO date
                last_seen   TEXT NOT NULL,       -- ISO date
                data        TEXT NOT NULL        -- JSON blob
            );

            CREATE INDEX IF NOT EXISTS idx_listings_last_seen
                ON listings (last_seen);

            CREATE TABLE IF NOT EXISTS daily_runs (
                run_date    TEXT PRIMARY KEY,
                sent_count  INTEGER DEFAULT 0,
                run_ts      TEXT NOT NULL
            );
        """)
    logger.info("Database initialised at %s", db_path)


def upsert_listing(db_path: str, listing: dict) -> bool:
    """
    Insert or update a listing.
    Returns True if this is a **new** listing (first time seen).
    """
    uid = f"{listing['source']}:{listing['source_id']}"
    today = date.today().isoformat()
    data_json = json.dumps(listing, ensure_ascii=False)

    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM listings WHERE id = ?", (uid,)
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO listings (id, source, source_id, first_seen, last_seen, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, listing["source"], listing["source_id"], today, today, data_json),
            )
            return True
        else:
            conn.execute(
                "UPDATE listings SET last_seen = ?, data = ? WHERE id = ?",
                (today, data_json, uid),
            )
            return False


def is_new_listing(db_path: str, source: str, source_id: str) -> bool:
    """Return True if this listing has never been stored before."""
    uid = f"{source}:{source_id}"
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM listings WHERE id = ?", (uid,)
        ).fetchone()
    return row is None


def get_listing(db_path: str, source: str, source_id: str) -> dict | None:
    uid = f"{source}:{source_id}"
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM listings WHERE id = ?", (uid,)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def record_daily_run(db_path: str, sent_count: int) -> None:
    from datetime import datetime
    today = date.today().isoformat()
    ts = datetime.now().isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_runs (run_date, sent_count, run_ts) "
            "VALUES (?, ?, ?)",
            (today, sent_count, ts),
        )
