from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import ReportRow
from .tracker import VoiceTracker

try:
    import discord
except ModuleNotFoundError:  # pragma: no cover - allows tests without discord.py installed
    discord = None


def format_seconds(total_seconds: int) -> str:
    """Render a duration as HH:MM:SS for consistent report output."""
    safe_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(safe_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


class GuildLike(Protocol):
    def get_member(self, user_id: int): ...


class ReportChannelLike(Protocol):
    async def send(self, content: str, **kwargs): ...


class Reporter:
    def __init__(self, tracker: VoiceTracker) -> None:
        self.tracker = tracker

    def build_rows_for_day(
        self,
        guild: GuildLike,
        day_local: str,
        *,
        include_live: bool,
        now_utc: datetime | None = None,
    ) -> list[ReportRow]:
        # Pull pre-aggregated totals (and optional live deltas), then map IDs to display names.
        totals = self.tracker.get_totals_for_day(day_local, include_live=include_live, now_utc=now_utc)

        rows: list[ReportRow] = []
        for user_id, seconds in totals.items():
            if seconds <= 0:
                continue

            member = guild.get_member(int(user_id))
            # Fall back to the raw ID when a member is no longer present in guild cache.
            display_name = member.display_name if member else f"User {user_id}"
            rows.append(ReportRow(user_id=user_id, display_name=display_name, seconds=seconds))

        rows.sort(key=lambda item: (-item.seconds, item.display_name.lower()))
        return rows

    def build_report_content(self, day_local: str, tracked_channel_name: str, rows: list[ReportRow]) -> str:
        header = f"**Daily Voice Activity - {day_local}**"
        channel_line = f"Tracked channel: #{tracked_channel_name}"

        if not rows:
            return f"{header}\n{channel_line}\nNo tracked activity for {day_local}."

        lines = [f"- {row.display_name}: `{format_seconds(row.seconds)}`" for row in rows]
        body = "\n".join(lines)
        return f"{header}\n{channel_line}\n{body}"

    async def post_report(
        self,
        guild: GuildLike,
        report_channel: ReportChannelLike,
        tracked_channel_name: str,
        day_local: str,
        *,
        include_live: bool,
        now_utc: datetime | None = None,
    ) -> bool:
        rows = self.build_rows_for_day(guild, day_local, include_live=include_live, now_utc=now_utc)
        content = self.build_report_content(day_local, tracked_channel_name, rows)

        kwargs = {}
        if discord is not None:
            # Never ping users in automated summaries.
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()

        await report_channel.send(content, **kwargs)
        return True
