from datetime import datetime, timezone


def parse_iso_utc(value):
    """Parse an ISO timestamp and normalize to UTC. Returns None if value is empty."""
    if not value:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        # Stored values should be timezone-aware; treat naive values as UTC for resilience.
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def remaining_cooldown_seconds(last_run_iso_utc, cooldown_seconds, now_utc):
    """Return remaining global cooldown seconds for /report-now."""
    if cooldown_seconds <= 0:
        return 0

    last_run = parse_iso_utc(last_run_iso_utc)
    if last_run is None:
        return 0

    elapsed = int((now_utc.astimezone(timezone.utc) - last_run).total_seconds())
    return max(0, cooldown_seconds - elapsed)
