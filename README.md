Telegram Streak Bot — Final (Variant A commands)

Features implemented:
- At 00:01 (TZ) sets waiting state and displays gray heart 🩶 next to streak number (if streak>0)
- On first user message during the day: increments streak, switches symbol to red heart ❤️ and updates title
- If no messages during the day (by 23:59), streak resets to 0 and title restored
- Auto-deletes service messages (such as 'chat title changed') and ignores them for activity
- Commands (short names):
  /help — show commands
  /streak — show current streak and symbol
  /set <n> — admin only, set streak manually
  /reset — admin only, reset streak
  /status — admin only, show stored data for this group
  /debug — admin only, dump global data (truncated)
  /force_tick — admin only, run 00:01 job manually
  /rename — admin only, force rename based on stored data
- Persists data in data.json

Deployment:
- Set BOT_TOKEN in env
- Optionally set TZ (defaults to UTC)
- Add bot to group, disable privacy in @BotFather, give admin rights: Change Info + Delete Messages for silent deletions

Notes:
- Some clients may still briefly show service messages before deletion depending on rights and timing.
