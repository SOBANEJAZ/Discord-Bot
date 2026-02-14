from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src import db
from src import tracker
from src.tracker import split_interval_by_local_day


def test_split_interval_crosses_local_midnight():
    tz = ZoneInfo("America/New_York")

    start_local = datetime(2026, 1, 1, 23, 50, tzinfo=tz)
    end_local = datetime(2026, 1, 2, 0, 10, tzinfo=tz)

    segments = split_interval_by_local_day(
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        tz,
    )

    assert segments == [("2026-01-01", 600), ("2026-01-02", 600)]


def test_accumulate_and_end_session_same_day():
    tz = ZoneInfo("UTC")
    db.connect_db(":memory:")
    db.initialize_db()

    start = datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, 10, 1, 30, tzinfo=timezone.utc)

    assert tracker.start_session("100", tz, started_at_utc=start) is True
    tracked = tracker.end_session("100", tz, ended_at_utc=end)

    assert tracked == 90

    totals = tracker.get_totals_for_day("2026-02-01", tz, include_live=False)
    assert totals == {"100": 90}

    db.close_db()


def test_include_live_totals_for_today():
    tz = ZoneInfo("UTC")
    db.connect_db(":memory:")
    db.initialize_db()

    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    db.add_daily_seconds("2026-02-01", "200", 120)
    db.set_open_session("200", datetime(2026, 2, 1, 11, 55, 0, tzinfo=timezone.utc))

    totals = tracker.get_totals_for_day("2026-02-01", tz, include_live=True, now_utc=now)

    assert totals["200"] == 420

    db.close_db()
