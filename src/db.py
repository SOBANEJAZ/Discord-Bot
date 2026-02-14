import sqlite3
from datetime import datetime, timezone

# Module-level connection — set by connect_db(), used by all other functions.
_connection = None


def connect_db(db_path):
    """Open a SQLite connection and store it at module level."""
    global _connection
    _connection = sqlite3.connect(str(db_path))
    _connection.row_factory = sqlite3.Row


def close_db():
    """Close the module-level SQLite connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def initialize_db():
    """Create the tables if they don't exist yet."""
    _connection.executescript(
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
    _connection.commit()


def set_open_session(user_id, started_at_utc):
    """Insert or update an open session for a user."""
    started = _to_utc(started_at_utc).isoformat()
    _connection.execute(
        """
        INSERT INTO open_sessions (user_id, started_at_utc)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET started_at_utc=excluded.started_at_utc
        """,
        (user_id, started),
    )
    _connection.commit()


def get_open_session(user_id):
    """Get one open session by user_id. Returns a dict or None."""
    row = _connection.execute(
        "SELECT user_id, started_at_utc FROM open_sessions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "started_at_utc": datetime.fromisoformat(row["started_at_utc"]),
    }


def delete_open_session(user_id):
    """Remove the open session for a user."""
    _connection.execute("DELETE FROM open_sessions WHERE user_id = ?", (user_id,))
    _connection.commit()


def clear_open_sessions():
    """Remove all open sessions."""
    _connection.execute("DELETE FROM open_sessions")
    _connection.commit()


def list_open_sessions():
    """Return all open sessions as a list of dicts."""
    rows = _connection.execute(
        "SELECT user_id, started_at_utc FROM open_sessions"
    ).fetchall()
    return [
        {
            "user_id": row["user_id"],
            "started_at_utc": datetime.fromisoformat(row["started_at_utc"]),
        }
        for row in rows
    ]


def add_daily_seconds(day_local, user_id, seconds):
    """Add tracked seconds for a user on a given local day. Ignores zero/negative values."""
    if seconds <= 0:
        return

    _connection.execute(
        """
        INSERT INTO daily_totals (day_local, user_id, seconds)
        VALUES (?, ?, ?)
        ON CONFLICT(day_local, user_id)
        DO UPDATE SET seconds = seconds + excluded.seconds
        """,
        (day_local, user_id, seconds),
    )
    _connection.commit()


def get_daily_totals(day_local):
    """Return all daily totals for a given day as a list of dicts."""
    rows = _connection.execute(
        """
        SELECT day_local, user_id, seconds
        FROM daily_totals
        WHERE day_local = ?
        ORDER BY seconds DESC, user_id ASC
        """,
        (day_local,),
    ).fetchall()

    return [
        {
            "day_local": row["day_local"],
            "user_id": row["user_id"],
            "seconds": row["seconds"],
        }
        for row in rows
    ]


def get_meta(key):
    """Read a value from the meta key/value store. Returns a string or None."""
    row = _connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_meta(key, value):
    """Write a value to the meta key/value store."""
    _connection.execute(
        """
        INSERT INTO meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    _connection.commit()


def _to_utc(value):
    """Normalize a timezone-aware datetime to UTC for storage."""
    if value.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    return value.astimezone(timezone.utc)
