from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class Config:
    discord_token: str
    guild_id: int
    tracked_voice_channel_id: int
    report_channel_id: int
    timezone: ZoneInfo
    report_now_cooldown_seconds: int


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def _required_int_env(name: str) -> int:
    value = _required_env(name)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc

    if parsed <= 0:
        raise ValueError(f"Environment variable {name} must be positive")
    return parsed


def _timezone_from_env(name: str) -> ZoneInfo:
    tz_name = _required_env(name)
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone in {name}: {tz_name}") from exc


def load_config() -> Config:
    cooldown_raw = os.getenv("REPORT_NOW_COOLDOWN_SECONDS", "3600").strip()
    try:
        cooldown = int(cooldown_raw)
    except ValueError as exc:
        raise ValueError("REPORT_NOW_COOLDOWN_SECONDS must be an integer") from exc

    if cooldown <= 0:
        raise ValueError("REPORT_NOW_COOLDOWN_SECONDS must be positive")

    return Config(
        discord_token=_required_env("DISCORD_TOKEN"),
        guild_id=_required_int_env("GUILD_ID"),
        tracked_voice_channel_id=_required_int_env("TRACKED_VOICE_CHANNEL_ID"),
        report_channel_id=_required_int_env("REPORT_CHANNEL_ID"),
        timezone=_timezone_from_env("TIMEZONE"),
        report_now_cooldown_seconds=cooldown,
    )
