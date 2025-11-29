# Telegram Streak Bot (Variant C — Production)
This bot tracks daily activity ("streak") per group and updates the group title with a flame emoji.

## Features
- Tracks daily activity (any message from 00:00 to 23:59 in TZ)
- Updates group title with " <streak>🔥"
- Commands:
  - /streak — show current streak
  - /set <number> — admin only, set streak
  - /reset — admin only, reset streak
  - /debug — admin only, dumps group data
  - /force_tick — admin only, run daily update immediately
  - /status — show stored data for group
  - /groups — admin only, list tracked groups
- Persists data in `data.json`
- Uses APScheduler to run daily at 00:00 in configured TZ (default Europe/Kyiv)

## Deployment (Railway)
1. Add repository files or upload the zip.
2. Set environment variable `BOT_TOKEN` to your bot token.
3. (Optional) set `TZ` (e.g. Europe/Kyiv) or `DATA_FILE`.
4. Start command: `python main.py` (Procfile included).

## Notes about "silent" title changes
Telegram shows a service message when the bot changes the chat title. The bot cannot make that silent. Optionally you can grant the bot "Delete messages" and implement logic to remove the service message, but it may not be reliable across all clients.
