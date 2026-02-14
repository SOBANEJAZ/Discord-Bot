import logging
from datetime import date, datetime, time, timedelta, timezone

from . import db


logger = logging.getLogger(__name__)


def utc_now():
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


def split_interval_by_local_day(start_utc, end_utc, tz):
    """Split a UTC interval into (local_day_iso, seconds) buckets.

    Returns a list of tuples like [("2026-01-01", 600), ("2026-01-02", 600)].
    """
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("start_utc and end_utc must be timezone-aware")

    start = start_utc.astimezone(timezone.utc)
    end = end_utc.astimezone(timezone.utc)

    if end <= start:
        return []

    segments = []
    cursor = start

    while cursor < end:
        # Convert the cursor into local time so midnight boundaries match the configured timezone.
        local_cursor = cursor.astimezone(tz)
        local_day = local_cursor.date()
        next_midnight_local = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=tz)
        next_midnight_utc = next_midnight_local.astimezone(timezone.utc)

        chunk_end = min(end, next_midnight_utc)
        chunk_seconds = int((chunk_end - cursor).total_seconds())

        if chunk_seconds > 0:
            segments.append((local_day.isoformat(), chunk_seconds))

        cursor = chunk_end

    return segments


def start_session(user_id, tz, started_at_utc=None):
    """Open a tracking session for a user. Returns True if started, False if already active."""
    if db.get_open_session(user_id) is not None:
        logger.debug("Ignoring duplicate start for user %s", user_id)
        return False

    started = started_at_utc or utc_now()
    db.set_open_session(user_id, started)
    return True


def end_session(user_id, tz, ended_at_utc=None):
    """Close a tracking session and persist the tracked seconds. Returns total seconds tracked."""
    session = db.get_open_session(user_id)
    if session is None:
        logger.debug("Ignoring stop for missing session user=%s", user_id)
        return 0

    ended = ended_at_utc or utc_now()
    tracked = accumulate_interval(user_id, session["started_at_utc"], ended, tz)
    db.delete_open_session(user_id)
    return tracked


def accumulate_interval(user_id, start_utc, end_utc, tz):
    """Split an interval across local days and persist each chunk. Returns total seconds."""
    total_seconds = 0
    for day_key, seconds in split_interval_by_local_day(start_utc, end_utc, tz):
        db.add_daily_seconds(day_key, user_id, seconds)
        total_seconds += seconds
    return total_seconds


def rollover_open_sessions(midnight_utc, tz):
    """At local midnight, close yesterday's portion and reopen at exactly midnight."""
    for session in db.list_open_sessions():
        if session["started_at_utc"] >= midnight_utc:
            continue
        accumulate_interval(session["user_id"], session["started_at_utc"], midnight_utc, tz)
        db.set_open_session(session["user_id"], midnight_utc)


def reseed_sessions(user_ids, started_at_utc=None):
    """On startup, reset open sessions to 'now' to avoid counting downtime."""
    started = started_at_utc or utc_now()
    db.clear_open_sessions()
    for user_id in user_ids:
        db.set_open_session(user_id, started)


def get_totals_for_day(day_local, tz, include_live=False, now_utc=None):
    """Get a dict of {user_id: seconds} for a given local day.

    If include_live is True, adds in-progress session time on top of persisted totals.
    """
    totals = {item["user_id"]: item["seconds"] for item in db.get_daily_totals(day_local)}

    if not include_live:
        return totals

    now = now_utc or utc_now()
    for session in db.list_open_sessions():
        for segment_day, seconds in split_interval_by_local_day(session["started_at_utc"], now, tz):
            if segment_day != day_local:
                continue
            totals[session["user_id"]] = totals.get(session["user_id"], 0) + seconds

    return totals


def local_day_key(tz, dt_utc=None):
    """Return today's date as an ISO string in the given timezone."""
    current = dt_utc or utc_now()
    return current.astimezone(tz).date().isoformat()


def previous_local_day_key(tz, dt_utc=None):
    """Return yesterday's date as an ISO string in the given timezone."""
    current = dt_utc or utc_now()
    local_date = current.astimezone(tz).date() - timedelta(days=1)
    return local_date.isoformat()


def midnight_utc_for_local_day(day_value, tz):
    """Convert a local date's midnight to a UTC datetime."""
    midnight_local = datetime.combine(day_value, time.min, tzinfo=tz)
    return midnight_local.astimezone(timezone.utc)
