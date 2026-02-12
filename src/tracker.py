from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .db import Database


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def split_interval_by_local_day(
    start_utc: datetime,
    end_utc: datetime,
    tz: ZoneInfo,
) -> list[tuple[str, int]]:
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("start_utc and end_utc must be timezone-aware")

    start = start_utc.astimezone(timezone.utc)
    end = end_utc.astimezone(timezone.utc)

    if end <= start:
        return []

    segments: list[tuple[str, int]] = []
    cursor = start

    while cursor < end:
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


class VoiceTracker:
    def __init__(self, db: Database, tz: ZoneInfo, logger: logging.Logger | None = None) -> None:
        self.db = db
        self.tz = tz
        self.logger = logger or logging.getLogger(__name__)

    def start_session(self, user_id: str, started_at_utc: datetime | None = None) -> bool:
        if self.db.get_open_session(user_id) is not None:
            self.logger.debug("Ignoring duplicate start for user %s", user_id)
            return False

        started = started_at_utc or utc_now()
        self.db.set_open_session(user_id, started)
        return True

    def end_session(self, user_id: str, ended_at_utc: datetime | None = None) -> int:
        session = self.db.get_open_session(user_id)
        if session is None:
            self.logger.debug("Ignoring stop for missing session user=%s", user_id)
            return 0

        ended = ended_at_utc or utc_now()
        tracked = self.accumulate_interval(user_id, session.started_at_utc, ended)
        self.db.delete_open_session(user_id)
        return tracked

    def accumulate_interval(self, user_id: str, start_utc: datetime, end_utc: datetime) -> int:
        total_seconds = 0
        for day_key, seconds in split_interval_by_local_day(start_utc, end_utc, self.tz):
            self.db.add_daily_seconds(day_key, user_id, seconds)
            total_seconds += seconds
        return total_seconds

    def rollover_open_sessions(self, midnight_utc: datetime) -> None:
        for session in self.db.list_open_sessions():
            if session.started_at_utc >= midnight_utc:
                continue
            self.accumulate_interval(session.user_id, session.started_at_utc, midnight_utc)
            self.db.set_open_session(session.user_id, midnight_utc)

    def reseed_sessions(self, user_ids: list[str], started_at_utc: datetime | None = None) -> None:
        started = started_at_utc or utc_now()
        self.db.clear_open_sessions()
        for user_id in user_ids:
            self.db.set_open_session(user_id, started)

    def get_totals_for_day(
        self,
        day_local: str,
        *,
        include_live: bool,
        now_utc: datetime | None = None,
    ) -> dict[str, int]:
        totals = {item.user_id: item.seconds for item in self.db.get_daily_totals(day_local)}

        if not include_live:
            return totals

        now = now_utc or utc_now()
        for session in self.db.list_open_sessions():
            for segment_day, seconds in split_interval_by_local_day(session.started_at_utc, now, self.tz):
                if segment_day != day_local:
                    continue
                totals[session.user_id] = totals.get(session.user_id, 0) + seconds

        return totals

    def local_day_key(self, dt_utc: datetime | None = None) -> str:
        current = dt_utc or utc_now()
        return current.astimezone(self.tz).date().isoformat()

    def previous_local_day_key(self, dt_utc: datetime | None = None) -> str:
        current = dt_utc or utc_now()
        local_date = current.astimezone(self.tz).date() - timedelta(days=1)
        return local_date.isoformat()

    def midnight_utc_for_local_day(self, day_value: date) -> datetime:
        midnight_local = datetime.combine(day_value, time.min, tzinfo=self.tz)
        return midnight_local.astimezone(timezone.utc)
