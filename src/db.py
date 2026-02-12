from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import DailyTotal, OpenSession


class Database:
    """Thin SQLite access layer for tracker state and aggregates."""

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._conn.close()
        self._closed = True

    def initialize(self) -> None:
        # open_sessions: currently connected users in the tracked channel.
        # daily_totals: aggregated seconds per local day and user.
        # meta: small key/value store for scheduler and cooldown markers.
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS open_sessions (
              user_id TEXT PRIMARY KEY,
              started_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_totals (
              day_local TEXT NOT NULL,
              user_id TEXT NOT NULL,
              seconds INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (day_local, user_id)
            );

            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def set_open_session(self, user_id: str, started_at_utc: datetime) -> None:
        started = _to_utc(started_at_utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO open_sessions (user_id, started_at_utc)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET started_at_utc=excluded.started_at_utc
            """,
            (user_id, started),
        )
        self._conn.commit()

    def get_open_session(self, user_id: str) -> OpenSession | None:
        row = self._conn.execute(
            "SELECT user_id, started_at_utc FROM open_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return OpenSession(user_id=row["user_id"], started_at_utc=datetime.fromisoformat(row["started_at_utc"]))

    def delete_open_session(self, user_id: str) -> None:
        self._conn.execute("DELETE FROM open_sessions WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def clear_open_sessions(self) -> None:
        self._conn.execute("DELETE FROM open_sessions")
        self._conn.commit()

    def list_open_sessions(self) -> list[OpenSession]:
        rows = self._conn.execute(
            "SELECT user_id, started_at_utc FROM open_sessions"
        ).fetchall()
        return [
            OpenSession(user_id=row["user_id"], started_at_utc=datetime.fromisoformat(row["started_at_utc"]))
            for row in rows
        ]

    def add_daily_seconds(self, day_local: str, user_id: str, seconds: int) -> None:
        # Ignore empty or negative spans so callers can pass raw calculations safely.
        if seconds <= 0:
            return

        self._conn.execute(
            """
            INSERT INTO daily_totals (day_local, user_id, seconds)
            VALUES (?, ?, ?)
            ON CONFLICT(day_local, user_id)
            DO UPDATE SET seconds = seconds + excluded.seconds
            """,
            (day_local, user_id, seconds),
        )
        self._conn.commit()

    def get_daily_totals(self, day_local: str) -> list[DailyTotal]:
        rows = self._conn.execute(
            """
            SELECT day_local, user_id, seconds
            FROM daily_totals
            WHERE day_local = ?
            ORDER BY seconds DESC, user_id ASC
            """,
            (day_local,),
        ).fetchall()

        return [
            DailyTotal(day_local=row["day_local"], user_id=row["user_id"], seconds=row["seconds"])
            for row in rows
        ]

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        self._conn.commit()


def _to_utc(value: datetime) -> datetime:
    """Normalize a timezone-aware datetime to UTC for storage."""
    if value.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    return value.astimezone(timezone.utc)
