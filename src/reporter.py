from datetime import datetime

from . import tracker

try:
    import discord
except ModuleNotFoundError:  # allows tests without discord.py installed
    discord = None


def format_seconds(total_seconds):
    """Render a duration as HH:MM:SS for consistent report output."""
    safe_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(safe_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def build_rows_for_day(guild, day_local, tz, include_live=False, now_utc=None):
    """Build a sorted list of report row dicts for a given day.

    Each row is a dict with keys: user_id, display_name, seconds.
    Sorted by most seconds first, then by name alphabetically.
    """
    totals = tracker.get_totals_for_day(day_local, tz, include_live=include_live, now_utc=now_utc)

    rows = []
    for user_id, seconds in totals.items():
        if seconds <= 0:
            continue

        member = guild.get_member(int(user_id))
        # Fall back to the raw ID when a member is no longer in the guild cache.
        display_name = member.display_name if member else f"User {user_id}"
        rows.append({"user_id": user_id, "display_name": display_name, "seconds": seconds})

    rows.sort(key=lambda item: (-item["seconds"], item["display_name"].lower()))
    return rows


def build_report_content(day_local, tracked_channel_name, rows):
    """Build the text content for a daily report message."""
    header = f"**Daily Voice Activity - {day_local}**"
    channel_line = f"Tracked channel: #{tracked_channel_name}"

    if not rows:
        return f"{header}\n{channel_line}\nNo tracked activity for {day_local}."

    lines = [f"- {row['display_name']}: `{format_seconds(row['seconds'])}`" for row in rows]
    body = "\n".join(lines)
    return f"{header}\n{channel_line}\n{body}"


async def post_report(guild, report_channel, tracked_channel_name, day_local, tz,
                      include_live=False, now_utc=None):
    """Build a report and send it to the report channel. Returns True on success."""
    rows = build_rows_for_day(guild, day_local, tz, include_live=include_live, now_utc=now_utc)
    content = build_report_content(day_local, tracked_channel_name, rows)

    kwargs = {}
    if discord is not None:
        # Never ping users in automated summaries.
        kwargs["allowed_mentions"] = discord.AllowedMentions.none()

    await report_channel.send(content, **kwargs)
    return True
