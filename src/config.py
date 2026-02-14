import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _required_env(name):
    """Read and trim a required environment variable."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def _required_int_env(name):
    """Parse a required positive integer environment variable."""
    value = _required_env(name)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc

    if parsed <= 0:
        raise ValueError(f"Environment variable {name} must be positive")
    return parsed


def _timezone_from_env(name):
    """Parse an IANA timezone name into a ZoneInfo instance."""
    tz_name = _required_env(name)
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone in {name}: {tz_name}") from exc


def load_config():
    """Load and validate all bot configuration from environment.

    Returns a plain dict with keys:
        discord_token, guild_id, tracked_voice_channel_id,
        report_channel_id, timezone, report_now_cooldown_seconds
    """
    cooldown_raw = os.getenv("REPORT_NOW_COOLDOWN_SECONDS", "3600").strip()
    try:
        cooldown = int(cooldown_raw)
    except ValueError as exc:
        raise ValueError("REPORT_NOW_COOLDOWN_SECONDS must be an integer") from exc

    if cooldown <= 0:
        raise ValueError("REPORT_NOW_COOLDOWN_SECONDS must be positive")

    return {
        "discord_token": _required_env("DISCORD_TOKEN"),
        "guild_id": _required_int_env("GUILD_ID"),
        "tracked_voice_channel_id": _required_int_env("TRACKED_VOICE_CHANNEL_ID"),
        "report_channel_id": _required_int_env("REPORT_CHANNEL_ID"),
        "timezone": _timezone_from_env("TIMEZONE"),
        "report_now_cooldown_seconds": cooldown,
    }
