from datetime import datetime, timezone

from src.cooldown import remaining_cooldown_seconds


def test_remaining_cooldown_seconds() -> None:
    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 2, 1, 11, 30, 0, tzinfo=timezone.utc).isoformat()

    assert remaining_cooldown_seconds(last_run, 3600, now) == 1800
    assert remaining_cooldown_seconds(last_run, 1200, now) == 0
    assert remaining_cooldown_seconds(None, 3600, now) == 0
