#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any

import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === CONFIG ===
TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN")
DATA_FILE = os.getenv("DATA_FILE", "data.json")
TZ = os.getenv("TZ", "Europe/Kyiv")  # timezone for daily tick

if TOKEN == "PUT_YOUR_TOKEN":
    # Friendly reminder; in prod override BOT_TOKEN env var
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)
data_lock = asyncio.Lock()

# Data structure:
# {
#   "<chat_id>": {
#       "streak": int,
#       "active_today": bool,
#       "original_title": str or None,
#       "last_updated": "YYYY-MM-DD" or None
#   },
#   ...
# }

def atomic_write(path: str, content: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

async def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load data.json, starting fresh")
        return {}

async def save_data(data: Dict[str, Any]):
    async with data_lock:
        atomic_write(DATA_FILE, json.dumps(data, ensure_ascii=False, indent=2))

def strip_streak_suffix(title: str) -> str:
    if not title:
        return title or ""
    # remove trailing " <num>🔥" possibly with spaces
    return re.sub(r"\s*\d+\s*🔥\s*$", "", title).strip()

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False

# === Handlers ===

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(
        "Привет! Я бот-стрик. Добавь меня в группу и дайте права администратора (Change Info).\n"
        "Команды для админов: /streak /set <число> /reset /force_tick\n"
        "Дополнительные команды: /debug /status /groups"
    )

@dp.message(Command("streak"))
async def cmd_streak(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply("Команда работает только в группах.")
    data = await load_data()
    entry = data.get(str(message.chat.id), {"streak": 0})
    await message.reply(f"Текущий стрик: {entry.get('streak', 0)}🔥")

@dp.message(Command("set"))
async def cmd_set(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply("Только в группах.")
    if not await is_user_admin(message.chat.id, message.from_user.id):
        return await message.reply("Только администраторы могут использовать эту команду.")
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.reply("Использование: /set <число>")
    val = int(parts[1])
    data = await load_data()
    cid = str(message.chat.id)
    entry = data.get(cid, {})
    entry.setdefault("original_title", None)
    entry["streak"] = val
    entry["active_today"] = False
    entry["last_updated"] = datetime.now(timezone.utc).date().isoformat()
    data[cid] = entry
    await save_data(data)

    # update title
    try:
        chat = await bot.get_chat(message.chat.id)
        base = entry.get("original_title") or strip_streak_suffix(chat.title or "")
        entry["original_title"] = base
        new_title = f"{base} {val}🔥" if val > 0 else base
        await bot.set_chat_title(message.chat.id, new_title)
        await save_data(data)
    except Exception:
        logger.exception("Failed to set chat title on /set")

    await message.reply(f"Стрик установлен: {val}🔥")

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply("Только в группах.")
    if not await is_user_admin(message.chat.id, message.from_user.id):
        return await message.reply("Только администраторы могут использовать эту команду.")
    data = await load_data()
    cid = str(message.chat.id)
    entry = data.get(cid, {})
    entry["streak"] = 0
    entry["active_today"] = False
    await save_data(data)

    # restore title
    try:
        chat = await bot.get_chat(message.chat.id)
        base = entry.get("original_title") or strip_streak_suffix(chat.title or "")
        await bot.set_chat_title(message.chat.id, base)
        entry["original_title"] = base
        await save_data(data)
    except Exception:
        logger.exception("Failed to restore title on /reset")
    await message.reply("Стрик обнулён.")

@dp.message(Command("debug"))
async def cmd_debug(message: types.Message):
    # admin-only
    if not await is_user_admin(message.chat.id, message.from_user.id):
        return await message.reply("Только админам.")
    data = await load_data()
    await message.reply(f"DATA: {json.dumps(data.get(str(message.chat.id), {}), ensure_ascii=False, indent=2)}")

@dp.message(Command("force_tick"))
async def cmd_force_tick(message: types.Message):
    # admin-only
    if not await is_user_admin(message.chat.id, message.from_user.id):
        return await message.reply("Только админам.")
    await run_daily_process()
    await message.reply("Принудительный тик выполнен.")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    data = await load_data()
    entry = data.get(str(message.chat.id), {})
    await message.reply(f"Status: {json.dumps(entry, ensure_ascii=False, indent=2)}")

@dp.message(Command("groups"))
async def cmd_groups(message: types.Message):
    # Admin-only global list
    if not await is_user_admin(message.chat.id, message.from_user.id):
        return await message.reply("Только админам.")
    data = await load_data()
    keys = list(data.keys())
    await message.reply(f"Tracked groups: {len(keys)}\n" + "\n".join(keys[:50]))

@dp.message()
async def handle_every_message(message: types.Message):
    # Track only in group chats
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    # ignore service messages
    if message.new_chat_title or message.new_chat_photo or message.left_chat_member or message.new_chat_members:
        return
    data = await load_data()
    cid = str(message.chat.id)
    entry = data.get(cid, {})
    if not entry:
        entry = {"streak": 0, "active_today": True, "original_title": None, "last_updated": None}
    else:
        entry["active_today"] = True
    data[cid] = entry
    await save_data(data)

# === Daily process ===
async def run_daily_process():
    tz = pytz.timezone(TZ)
    today = datetime.now(tz).date().isoformat()
    data = await load_data()
    changed = False
    for cid, entry in list(data.items()):
        active = entry.get("active_today", False)
        streak = int(entry.get("streak", 0))
        if active:
            streak += 1
            entry["last_updated"] = today
        else:
            streak = 0
        entry["streak"] = streak
        entry["active_today"] = False
        # update title if possible
        try:
            chat = await bot.get_chat(int(cid))
            base = entry.get("original_title") or strip_streak_suffix(chat.title or "")
            entry["original_title"] = base
            new_title = f"{base} {streak}🔥" if streak > 0 else base
            # only set title if changed
            if (chat.title or "") != new_title:
                await bot.set_chat_title(int(cid), new_title)
        except Exception:
            logger.exception("Failed to update title for %s", cid)
        data[cid] = entry
        changed = True
    if changed:
        await save_data(data)

async def on_startup():
    # schedule job at 00:00 in TZ
    scheduler.add_job(run_daily_process, 'cron', hour=0, minute=0)
    scheduler.start()
    logger.info("Scheduler started (daily at 00:00 %s)", TZ)

async def main():
    await on_startup()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
