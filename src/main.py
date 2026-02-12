from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from .commands import register_commands
from .config import Config, load_config
from .cooldown import remaining_cooldown_seconds
from .db import Database
from .reporter import Reporter
from .tracker import VoiceTracker, utc_now

AUTO_REPORT_META_KEY = "last_auto_report_day"
MANUAL_REPORT_META_KEY = "last_manual_report_at_utc"
DEFAULT_DB_PATH = Path("voice_tracker.db")


class VoiceTrackerBot(commands.Bot):
    def __init__(self, config: Config, db: Database) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True

        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.db = db
        self.tracker = VoiceTracker(db=db, tz=config.timezone)
        self.reporter = Reporter(self.tracker)

        self.logger = logging.getLogger("voice-tracker-bot")

        # runtime_ready prevents event handlers from running before channel/permission checks pass.
        self.runtime_ready = False
        self.guild_obj: discord.Guild | None = None
        self.tracked_voice_channel: discord.VoiceChannel | None = None
        self.report_channel: discord.TextChannel | None = None

    async def setup_hook(self) -> None:
        # Register slash commands during startup and begin the midnight scheduler loop.
        register_commands(self)
        await self.tree.sync(guild=discord.Object(id=self.config.guild_id))
        self.midnight_report_loop.start()

    async def on_ready(self) -> None:
        self.logger.info("Connected as %s (%s)", self.user, self.user.id if self.user else "unknown")
        if self.runtime_ready:
            return

        if await self._validate_runtime_resources():
            self.runtime_ready = True
            self.logger.info("Runtime checks passed")

    async def _validate_runtime_resources(self) -> bool:
        # Fail fast if guild/channels/permissions are misconfigured.
        guild = self.get_guild(self.config.guild_id)
        if guild is None:
            self.logger.error("Configured guild %s not found", self.config.guild_id)
            await self.close()
            return False

        tracked = guild.get_channel(self.config.tracked_voice_channel_id)
        if not isinstance(tracked, discord.VoiceChannel):
            self.logger.error("Tracked channel %s is missing or not a voice channel", self.config.tracked_voice_channel_id)
            await self.close()
            return False

        report = guild.get_channel(self.config.report_channel_id)
        if not isinstance(report, discord.TextChannel):
            self.logger.error("Report channel %s is missing or not a text channel", self.config.report_channel_id)
            await self.close()
            return False

        me = guild.me
        if me is None and self.user is not None:
            me = guild.get_member(self.user.id)

        if me is None:
            self.logger.error("Unable to resolve bot member in guild %s", guild.id)
            await self.close()
            return False

        perms = report.permissions_for(me)
        if not perms.view_channel or not perms.send_messages:
            self.logger.error("Missing view/send permission in report channel %s", report.id)
            await self.close()
            return False

        self.guild_obj = guild
        self.tracked_voice_channel = tracked
        self.report_channel = report

        self._reseed_open_sessions_from_channel()
        return True

    def _reseed_open_sessions_from_channel(self) -> None:
        if self.tracked_voice_channel is None:
            return

        now = utc_now()
        # Ignore bot accounts so only human members appear in tracked totals.
        active_users = [str(member.id) for member in self.tracked_voice_channel.members if not member.bot]
        self.tracker.reseed_sessions(active_users, started_at_utc=now)
        self.logger.info("Reseeded open sessions for %d active users", len(active_users))

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if not self.runtime_ready:
            return

        if member.bot:
            return

        if member.guild.id != self.config.guild_id:
            return

        tracked_channel_id = self.config.tracked_voice_channel_id
        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None

        now = utc_now()
        user_id = str(member.id)

        # Enter tracked channel => open a session.
        if before_id != tracked_channel_id and after_id == tracked_channel_id:
            if self.tracker.start_session(user_id, started_at_utc=now):
                self.logger.info("Session started: user=%s", user_id)
            return

        # Leave tracked channel => close and persist the session.
        if before_id == tracked_channel_id and after_id != tracked_channel_id:
            tracked_seconds = self.tracker.end_session(user_id, ended_at_utc=now)
            self.logger.info("Session ended: user=%s tracked=%ss", user_id, tracked_seconds)

    @tasks.loop(seconds=30)
    async def midnight_report_loop(self) -> None:
        if not self.runtime_ready:
            return

        now = utc_now()
        now_local = now.astimezone(self.config.timezone)

        # The loop runs every 30s; only execute report logic during 00:00 local minute.
        if now_local.hour != 0 or now_local.minute != 0:
            return

        target_day = (now_local.date() - timedelta(days=1)).isoformat()
        # Guard against duplicate posts during the same 00:00 minute window.
        if self.db.get_meta(AUTO_REPORT_META_KEY) == target_day:
            return

        if self.guild_obj is None or self.report_channel is None:
            self.logger.error("Runtime resources unavailable while trying to post midnight report")
            return

        midnight_local = datetime.combine(now_local.date(), time.min, tzinfo=self.config.timezone)
        midnight_utc = midnight_local.astimezone(timezone.utc)

        # Close yesterday's slice for users still connected at midnight.
        self.tracker.rollover_open_sessions(midnight_utc)

        tracked_name = str(self.config.tracked_voice_channel_id)
        if self.tracked_voice_channel is not None:
            tracked_name = self.tracked_voice_channel.name

        self.logger.info("Posting midnight report for %s", target_day)

        try:
            await self.reporter.post_report(
                self.guild_obj,
                self.report_channel,
                tracked_name,
                target_day,
                include_live=False,
                now_utc=midnight_utc,
            )
        except Exception:  # pragma: no cover - runtime safety
            self.logger.exception("Failed to post midnight report")
            return

        self.db.set_meta(AUTO_REPORT_META_KEY, target_day)

    @midnight_report_loop.before_loop
    async def before_midnight_report_loop(self) -> None:
        await self.wait_until_ready()

    def cooldown_remaining_seconds(self, now_utc: datetime | None = None) -> int:
        now = now_utc or utc_now()
        last_manual = self.db.get_meta(MANUAL_REPORT_META_KEY)
        return remaining_cooldown_seconds(
            last_manual,
            self.config.report_now_cooldown_seconds,
            now,
        )

    def record_manual_report(self, now_utc: datetime | None = None) -> None:
        # Persist global cooldown reference timestamp for /report-now.
        now = (now_utc or utc_now()).astimezone(timezone.utc)
        self.db.set_meta(MANUAL_REPORT_META_KEY, now.isoformat())

    async def close(self) -> None:
        if self.midnight_report_loop.is_running():
            self.midnight_report_loop.cancel()
        self.db.close()
        await super().close()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    load_dotenv()
    configure_logging()

    config = load_config()
    db = Database(DEFAULT_DB_PATH)
    db.initialize()

    bot = VoiceTrackerBot(config=config, db=db)
    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
