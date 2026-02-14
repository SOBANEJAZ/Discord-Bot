import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from . import db, reporter, tracker
from .commands import register_commands
from .config import load_config
from .tracker import utc_now

AUTO_REPORT_META_KEY = "last_auto_report_day"
MANUAL_REPORT_META_KEY = "last_manual_report_at_utc"
DEFAULT_DB_PATH = Path("voice_tracker.db")


def create_bot(config):
    """Create and configure the Discord bot with all event handlers.

    This is the main setup function — it wires together the config, database,
    tracker, and reporter into a single bot instance.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    # Attach config and runtime state directly on the bot object.
    bot.config = config
    bot.logger = logging.getLogger("voice-tracker-bot")
    bot.runtime_ready = False
    bot.guild_obj = None
    bot.tracked_voice_channel = None
    bot.report_channel = None

    # --- Event Handlers ---

    @bot.event
    async def setup_hook():
        """Called automatically by discord.py during startup."""
        register_commands(bot)
        await bot.tree.sync(guild=discord.Object(id=config["guild_id"]))
        midnight_report_loop.start()

    @bot.event
    async def on_ready():
        bot.logger.info("Connected as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
        if bot.runtime_ready:
            return

        if await validate_runtime(bot, config):
            bot.runtime_ready = True
            bot.logger.info("Runtime checks passed")

    @bot.event
    async def on_voice_state_update(member, before, after):
        if not bot.runtime_ready:
            return
        if member.bot:
            return
        if member.guild.id != config["guild_id"]:
            return

        tracked_channel_id = config["tracked_voice_channel_id"]
        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None

        now = utc_now()
        user_id = str(member.id)
        tz = config["timezone"]

        # Enter tracked channel => open a session.
        if before_id != tracked_channel_id and after_id == tracked_channel_id:
            if tracker.start_session(user_id, tz, started_at_utc=now):
                bot.logger.info("Session started: user=%s", user_id)
            return

        # Leave tracked channel => close and persist the session.
        if before_id == tracked_channel_id and after_id != tracked_channel_id:
            tracked_seconds = tracker.end_session(user_id, tz, ended_at_utc=now)
            bot.logger.info("Session ended: user=%s tracked=%ss", user_id, tracked_seconds)

    # --- Midnight Report Loop ---

    @tasks.loop(seconds=30)
    async def midnight_report_loop():
        if not bot.runtime_ready:
            return

        now = utc_now()
        tz = config["timezone"]
        now_local = now.astimezone(tz)

        # Only execute report logic during 00:00 local minute.
        if now_local.hour != 0 or now_local.minute != 0:
            return

        target_day = (now_local.date() - timedelta(days=1)).isoformat()
        # Guard against duplicate posts during the same 00:00 minute window.
        if db.get_meta(AUTO_REPORT_META_KEY) == target_day:
            return

        if bot.guild_obj is None or bot.report_channel is None:
            bot.logger.error("Runtime resources unavailable while trying to post midnight report")
            return

        midnight_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
        midnight_utc = midnight_local.astimezone(timezone.utc)

        # Close yesterday's slice for users still connected at midnight.
        tracker.rollover_open_sessions(midnight_utc, tz)

        tracked_name = str(config["tracked_voice_channel_id"])
        if bot.tracked_voice_channel is not None:
            tracked_name = bot.tracked_voice_channel.name

        bot.logger.info("Posting midnight report for %s", target_day)

        try:
            await reporter.post_report(
                bot.guild_obj,
                bot.report_channel,
                tracked_name,
                target_day,
                tz,
                include_live=False,
                now_utc=midnight_utc,
            )
        except Exception:
            bot.logger.exception("Failed to post midnight report")
            return

        db.set_meta(AUTO_REPORT_META_KEY, target_day)

    @midnight_report_loop.before_loop
    async def before_midnight_report_loop():
        await bot.wait_until_ready()

    # Store the loop on the bot so we can cancel it on close.
    bot._midnight_loop = midnight_report_loop

    # Override close to clean up resources.
    original_close = bot.close

    async def custom_close():
        if midnight_report_loop.is_running():
            midnight_report_loop.cancel()
        db.close_db()
        await original_close()

    bot.close = custom_close

    return bot


async def validate_runtime(bot, config):
    """Verify guild, channels, and permissions are set up correctly."""
    guild = bot.get_guild(config["guild_id"])
    if guild is None:
        bot.logger.error("Configured guild %s not found", config["guild_id"])
        await bot.close()
        return False

    tracked = guild.get_channel(config["tracked_voice_channel_id"])
    if not isinstance(tracked, discord.VoiceChannel):
        bot.logger.error("Tracked channel %s is missing or not a voice channel", config["tracked_voice_channel_id"])
        await bot.close()
        return False

    report = guild.get_channel(config["report_channel_id"])
    if not isinstance(report, discord.TextChannel):
        bot.logger.error("Report channel %s is missing or not a text channel", config["report_channel_id"])
        await bot.close()
        return False

    me = guild.me
    if me is None and bot.user is not None:
        me = guild.get_member(bot.user.id)

    if me is None:
        bot.logger.error("Unable to resolve bot member in guild %s", guild.id)
        await bot.close()
        return False

    perms = report.permissions_for(me)
    if not perms.view_channel or not perms.send_messages:
        bot.logger.error("Missing view/send permission in report channel %s", report.id)
        await bot.close()
        return False

    bot.guild_obj = guild
    bot.tracked_voice_channel = tracked
    bot.report_channel = report

    reseed_from_channel(bot, config)
    return True


def reseed_from_channel(bot, config):
    """Reset open sessions based on who's currently in the tracked voice channel."""
    if bot.tracked_voice_channel is None:
        return

    now = utc_now()
    # Ignore bot accounts so only human members appear in tracked totals.
    active_users = [str(member.id) for member in bot.tracked_voice_channel.members if not member.bot]
    tracker.reseed_sessions(active_users, started_at_utc=now)
    bot.logger.info("Reseeded open sessions for %d active users", len(active_users))


def configure_logging():
    """Set up basic logging format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main():
    """Entry point — load config, connect DB, create bot, and run."""
    load_dotenv()
    configure_logging()

    config = load_config()
    db.connect_db(DEFAULT_DB_PATH)
    db.initialize_db()

    bot = create_bot(config)
    bot.run(config["discord_token"])


if __name__ == "__main__":
    main()
