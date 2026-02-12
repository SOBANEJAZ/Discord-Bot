from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.db import Database
from src.reporter import Reporter, format_seconds
from src.tracker import VoiceTracker


class FakeMember:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


class FakeGuild:
    def __init__(self) -> None:
        self.members = {
            1: FakeMember("Alice"),
            2: FakeMember("Bob"),
        }

    def get_member(self, user_id: int):
        return self.members.get(user_id)


def test_format_seconds_hh_mm_ss() -> None:
    assert format_seconds(0) == "00:00:00"
    assert format_seconds(3661) == "01:01:01"


def test_report_rows_sorted_by_seconds_desc() -> None:
    db = Database(":memory:")
    db.initialize()
    tracker = VoiceTracker(db=db, tz=ZoneInfo("UTC"))
    reporter = Reporter(tracker)

    db.add_daily_seconds("2026-02-01", "1", 100)
    db.add_daily_seconds("2026-02-01", "2", 300)

    rows = reporter.build_rows_for_day(FakeGuild(), "2026-02-01", include_live=False)

    assert [row.display_name for row in rows] == ["Bob", "Alice"]
    assert [row.seconds for row in rows] == [300, 100]


def test_no_activity_message() -> None:
    db = Database(":memory:")
    db.initialize()
    tracker = VoiceTracker(db=db, tz=ZoneInfo("UTC"))
    reporter = Reporter(tracker)

    content = reporter.build_report_content("2026-02-01", "focus-room", [])

    assert "No tracked activity for 2026-02-01." in content
