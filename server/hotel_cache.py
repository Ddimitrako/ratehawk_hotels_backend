from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple
import time


class HotelInfoStore:
    """Tiny SQLite-backed cache for Hotel Info payloads keyed by (id, language).

    Stores sanitized JSON payloads (the full HotelInfoResponse as dict) to avoid
    re-fetching the same content and hitting upstream rate limits.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(os.path.dirname(db_path) or ".").mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hotels (
                    id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at INTEGER,
                    PRIMARY KEY (id, language)
                )
                """
            )
            # Migrate older schema without updated_at
            try:
                cols = {r[1] for r in con.execute("PRAGMA table_info(hotels)").fetchall()}
                if "updated_at" not in cols:
                    con.execute("ALTER TABLE hotels ADD COLUMN updated_at INTEGER")
                # Fill missing timestamps
                con.execute("UPDATE hotels SET updated_at = ? WHERE updated_at IS NULL", (int(time.time()),))
            except Exception:
                pass

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def get(self, hotel_id: str, language: str) -> Optional[dict]:
        with self._conn() as con:
            cur = con.execute(
                "SELECT payload FROM hotels WHERE id = ? AND language = ?",
                (hotel_id, language),
            )
            row = cur.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except Exception:
                return None

    def set(self, hotel_id: str, language: str, payload: dict) -> None:
        with self._conn() as con:
            con.execute(
                "REPLACE INTO hotels (id, language, payload, updated_at) VALUES (?, ?, ?, ?)",
                (hotel_id, language, json.dumps(payload), int(time.time())),
            )

    def stats(self) -> Tuple[int, Optional[int]]:
        with self._conn() as con:
            cur = con.execute("SELECT COUNT(*), MAX(updated_at) FROM hotels")
            row = cur.fetchone()
            if not row:
                return 0, None
            count = int(row[0] or 0)
            last = int(row[1]) if row[1] is not None else None
            return count, last
