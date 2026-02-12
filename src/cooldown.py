from __future__ import annotations

from datetime import datetime, timezone


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO timestamp and normalize to UTC."""
    if not value:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        # Stored values should be timezone-aware; treat naive values as UTC for resilience.
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def remaining_cooldown_seconds(
    last_run_iso_utc: str | None,
    cooldown_seconds: int,
    now_utc: datetime,
) -> int:
    """Return remaining global cooldown seconds for /report-now."""
    if cooldown_seconds <= 0:
        return 0

    last_run = parse_iso_utc(last_run_iso_utc)
    if last_run is None:
        return 0

    elapsed = int((now_utc.astimezone(timezone.utc) - last_run).total_seconds())
    return max(0, cooldown_seconds - elapsed)
