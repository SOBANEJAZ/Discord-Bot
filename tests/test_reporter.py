from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src import db, reporter


class FakeMember:
    def __init__(self, display_name):
        self.display_name = display_name


class FakeGuild:
    def __init__(self):
        self.members = {
            1: FakeMember("Alice"),
            2: FakeMember("Bob"),
        }

    def get_member(self, user_id):
        return self.members.get(user_id)


def test_format_seconds_hh_mm_ss():
    assert reporter.format_seconds(0) == "00:00:00"
    assert reporter.format_seconds(3661) == "01:01:01"


def test_report_rows_sorted_by_seconds_desc():
    db.connect_db(":memory:")
    db.initialize_db()

    db.add_daily_seconds("2026-02-01", "1", 100)
    db.add_daily_seconds("2026-02-01", "2", 300)

    tz = ZoneInfo("UTC")
    rows = reporter.build_rows_for_day(FakeGuild(), "2026-02-01", tz, include_live=False)

    assert [row["display_name"] for row in rows] == ["Bob", "Alice"]
    assert [row["seconds"] for row in rows] == [300, 100]

    db.close_db()


def test_no_activity_message():
    content = reporter.build_report_content("2026-02-01", "focus-room", [])

    assert "No tracked activity for 2026-02-01." in content
