from datetime import datetime, time, timedelta, timezone

import discord

from . import db, reporter
from .cooldown import remaining_cooldown_seconds
from .reporter import format_seconds
from .tracker import utc_now


MANUAL_REPORT_META_KEY = "last_manual_report_at_utc"


def register_commands(bot):
    """Register all slash commands on the bot. Called once during setup."""
    guild_scope = discord.Object(id=bot.config["guild_id"])

    @bot.tree.command(name="status", description="Show bot status and cooldown info", guild=guild_scope)
    async def status(interaction):
        now = utc_now()
        now_local = now.astimezone(bot.config["timezone"])
        next_midnight_local = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=bot.config["timezone"])

        # Calculate cooldown inline instead of calling a method
        last_manual = db.get_meta(MANUAL_REPORT_META_KEY)
        cooldown_remaining = remaining_cooldown_seconds(
            last_manual, bot.config["report_now_cooldown_seconds"], now
        )

        lines = [
            "Voice tracker status: online",
            f"Guild ID: `{bot.config['guild_id']}`",
            f"Tracked voice channel ID: `{bot.config['tracked_voice_channel_id']}`",
            f"Report channel ID: `{bot.config['report_channel_id']}`",
            f"Timezone: `{bot.config['timezone'].key}`",
            f"Current local time: `{now_local.isoformat()}`",
            f"Next scheduled midnight check: `{next_midnight_local.isoformat()}`",
            f"/report-now cooldown remaining: `{format_seconds(cooldown_remaining)}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @bot.tree.command(name="today", description="Show today's tracked totals so far", guild=guild_scope)
    async def today(interaction):
        if interaction.guild is None or interaction.guild.id != bot.config["guild_id"]:
            await interaction.response.send_message("This command can only be used in the configured server.", ephemeral=True)
            return

        now = utc_now()
        day_local = now.astimezone(bot.config["timezone"]).date().isoformat()
        tz = bot.config["timezone"]

        rows = reporter.build_rows_for_day(
            interaction.guild, day_local, tz, include_live=True, now_utc=now
        )

        if not rows:
            await interaction.response.send_message(
                f"No tracked activity for {day_local}.",
                ephemeral=True,
            )
            return

        lines = [f"Today's totals ({day_local}):"]
        lines.extend(f"- {row['display_name']}: `{format_seconds(row['seconds'])}`" for row in rows)
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @bot.tree.command(name="report-now", description="Post a manual day-so-far report", guild=guild_scope)
    async def report_now(interaction):
        if interaction.guild is None or interaction.guild.id != bot.config["guild_id"]:
            await interaction.response.send_message("This command can only be used in the configured server.", ephemeral=True)
            return

        now = utc_now()
        tz = bot.config["timezone"]

        # Calculate cooldown inline
        last_manual = db.get_meta(MANUAL_REPORT_META_KEY)
        cooldown_remaining = remaining_cooldown_seconds(
            last_manual, bot.config["report_now_cooldown_seconds"], now
        )
        if cooldown_remaining > 0:
            await interaction.response.send_message(
                f"Global cooldown active. Try again in `{format_seconds(cooldown_remaining)}`.",
                ephemeral=True,
            )
            return

        if bot.report_channel is None:
            await interaction.response.send_message("Report channel is not available.", ephemeral=True)
            return

        tracked_name = str(bot.config["tracked_voice_channel_id"])
        if bot.tracked_voice_channel is not None:
            tracked_name = bot.tracked_voice_channel.name

        day_local = now.astimezone(tz).date().isoformat()

        try:
            await reporter.post_report(
                interaction.guild,
                bot.report_channel,
                tracked_name,
                day_local,
                tz,
                include_live=True,
                now_utc=now,
            )
        except Exception as exc:
            bot.logger.exception("/report-now failed")
            await interaction.response.send_message(f"Failed to send report: `{exc}`", ephemeral=True)
            return

        # Record the manual report time for cooldown tracking
        now_iso = now.astimezone(timezone.utc).isoformat()
        db.set_meta(MANUAL_REPORT_META_KEY, now_iso)

        await interaction.response.send_message(
            f"Posted day-so-far report for `{day_local}` in <#{bot.config['report_channel_id']}>.",
            ephemeral=True,
        )
