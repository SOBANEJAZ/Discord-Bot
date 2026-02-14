# Discord Voice Tracker Bot

A Discord bot that tracks time spent in one voice channel, stores daily totals, and posts a midnight summary.

## Features

- Tracks per-user time in one configured voice channel
- Splits sessions exactly at local midnight
- Posts automatic summary at `00:00` local time for the previous day
- Commands:
  - `/status`
  - `/today`
  - `/report-now`
- Stores data in SQLite (`voice_tracker.db`)

## Requirements

- Python 3.11+
- Discord bot with `Guilds` and `Voice States` intents enabled

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -e .
```

3. Copy `.env.example` to `.env` and fill the values.
4. Run:

```bash
python -m src.main
```

## Configuration

- `DISCORD_TOKEN`: bot token
- `GUILD_ID`: target server ID
- `TRACKED_VOICE_CHANNEL_ID`: channel to track
- `REPORT_CHANNEL_ID`: channel where reports are posted
- `TIMEZONE`: IANA timezone (for example `America/New_York`)

## systemd example

```ini
[Unit]
Description=Discord Voice Tracker Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/discord-voice-tracker
ExecStart=/opt/discord-voice-tracker/.venv/bin/python -m src.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

## Notes

- The bot skips missed midnight reports while offline (v1 behavior).
- On startup, open sessions are reseeded from users currently connected to the tracked channel.
