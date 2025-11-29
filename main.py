import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone, date
from typing import Dict, Any

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from dateutil import parser as dt_parser

# ---------------- CONFIG ----------------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")

DATA_FILE = os.getenv("DATA_FILE", "data.json")
# timezone for daily reset / cron
TZ = os.getenv("TZ", "Europe/Kyiv")  # user's timezone as requested

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- GLOBALS ----------------
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
data_lock = asyncio.Lock()

# data structure:
# {
#   "<chat_id>": {
#       "streak": int,
#       "last_active_date": "YYYY-MM-DD" or None,
#       "active_today": bool
#   },
#   ...
# }
DATA: Dict[str, Dict[str, Any]] = {}


# ---------------- UTIL ----------------
def load_data():
    global DATA
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            DATA = json.load(f)
            logger.info("Loaded data.json with %d chats", len(DATA))
    except FileNotFoundError:
        DATA = {}
        logger.info("data.json not found, starting fresh")
    except Exception as e:
        logger.exception("Failed to load data.json: %s", e)
        DATA = {}


async def save_data():
    async with data_lock:
        tmp = DATA.copy()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(tmp, f, ensure_ascii=False, indent=2)
        logger.debug("Saved data.json")


def normalize_chat_id(chat_id: int) -> str:
    return str(chat_id)


def strip_streak_from_title(title: str) -> str:
    """Remove trailing ' <num>🔥' if present (and any trailing spaces)."""
    if not title:
        return title
    # remove patterns like " 14🔥" or " 14 🔥"
    new = re.sub(r"\s*\d+\s*🔥\s*$", "", title)
    return new.strip()


async def set_chat_title_safely(chat_id: int, base_title: str, streak: int):
    """
    Set chat title to base_title + ' {streak}🔥'.
    Note: Telegram will create a service message about title change; see README note.
    """
    new_title = f"{base_title} {streak}🔥"
    try:
        await bot.set_chat_title(chat_id, new_title)
        logger.info("Set chat (%s) title to: %s", chat_id, new_title)
    except Exception as e:
        logger.exception("Failed to set chat title for %s: %s", chat_id, e)


async def safe_get_chat_title(chat_id: int) -> str:
    try:
        ch = await bot.get_chat(chat_id)
        return getattr(ch, "title", "") or ""
    except Exception as e:
        logger.warning("Cannot get chat title for %s: %s", chat_id, e)
        return ""


def today_str(tz_name: str = TZ) -> str:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).date().isoformat()


# ---------------- MESSAGE HANDLERS ----------------
@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    await message.reply(
        "Привет! Я бот-стрик. Добавь меня в группу как администратора (нужны права менять название) — "
        "я буду вести ежедневный стрик активности и добавлять в название группы число с огоньком.\n\n"
        "Команды для админов в группе:\n"
        "/streak — показать текущий стрик\n"
        "/set <число> — установить стрик вручную\n"
        "/reset — сброс стрика\n\n"
        "Бот хранит данные в data.json и работает 24/7."
    )


@dp.message_handler(commands=["streak"])
async def cmd_streak(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Команда работает только в группах.")
        return

    chat_id = normalize_chat_id(message.chat.id)
    entry = DATA.get(chat_id, {"streak": 0})
    await message.reply(f"Текущий стрик: {entry.get('streak', 0)} 🔥")


async def is_user_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


@dp.message_handler(commands=["set"])
async def cmd_set(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Команда работает только в группах.")
        return

    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("Только администраторы могут использовать эту команду.")
        return

    args = message.get_args().strip()
    if not args or not re.match(r"^\d+$", args):
        await message.reply("Использование: /set <число>")
        return

    val = int(args)
    chat_id = normalize_chat_id(message.chat.id)
    async with data_lock:
        entry = DATA.get(chat_id, {"streak": 0, "last_active_date": None, "active_today": False})
        entry["streak"] = val
        DATA[chat_id] = entry
        await save_data()

    # update title immediately
    base_title = strip_streak_from_title(await safe_get_chat_title(message.chat.id))
    await set_chat_title_safely(message.chat.id, base_title, val)

    await message.reply(f"Стрик установлен: {val} 🔥")


@dp.message_handler(commands=["reset"])
async def cmd_reset(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Команда работает только в группах.")
        return

    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("Только администраторы могут использовать эту команду.")
        return

    chat_id = normalize_chat_id(message.chat.id)
    async with data_lock:
        entry = DATA.get(chat_id, {"streak": 0, "last_active_date": None, "active_today": False})
        entry["streak"] = 0
        entry["active_today"] = False
        DATA[chat_id] = entry
        await save_data()

    base_title = strip_streak_from_title(await safe_get_chat_title(message.chat.id))
    await set_chat_title_safely(message.chat.id, base_title, 0)

    await message.reply("Стрик обнулён.")


@dp.message_handler(content_types=types.ContentTypes.ANY)
async def catch_all_messages(message: types.Message):
    # Only track messages from groups (not private chats)
    if message.chat.type not in ("group", "supergroup"):
        return

    # ignore service messages (optional)
    if getattr(message, "new_chat_title", None) or getattr(message, "new_chat_photo", None):
        # don't count these as activity
        return

    chat_id = normalize_chat_id(message.chat.id)
    today = today_str()

    async with data_lock:
        entry = DATA.get(chat_id)
        if not entry:
            entry = {"streak": 0, "last_active_date": None, "active_today": False}
        # if last_active_date is not today, but someone wrote today => mark active_today True
        if entry.get("last_active_date") != today:
            entry["active_today"] = True
        else:
            # already marked today
            entry["active_today"] = True
        DATA[chat_id] = entry
        # persist occasionally (could be optimized)
        await save_data()


# ---------------- DAILY JOB ----------------
async def daily_process():
    """
    Runs once per day at 00:00 (TZ). For each tracked chat:
      - if active_today == True -> streak +=1 and last_active_date = today
      - else -> streak = 0
    Then update group title to include streak.
    Reset active_today to False (for the new day)
    """
    logger.info("Running daily process")
    async with data_lock:
        items = list(DATA.items())

    tz = pytz.timezone(TZ)
    today = datetime.now(tz).date().isoformat()
    tasks = []

    for chat_id_str, entry in items:
        chat_id = int(chat_id_str)
        active = entry.get("active_today", False)
        streak = int(entry.get("streak", 0))
        last = entry.get("last_active_date")

        if active:
            streak = streak + 1
            last = today
        else:
            streak = 0
            # last stays as-is (or None)

        # update entry
        async with data_lock:
            DATA[chat_id_str] = {
                "streak": streak,
                "last_active_date": last,
                "active_today": False  # reset for next day
            }
            await save_data()

        # prepare title update
        tasks.append((chat_id, streak))

    # update titles in parallel (but not too many at once)
    # We'll run them sequentially with small concurrency to be safe
    sem = asyncio.Semaphore(8)

    async def update_title(chat_id, streak):
        async with sem:
            base_title = strip_streak_from_title(await safe_get_chat_title(chat_id))
            if not base_title:
                # if no title (rare for some chat types), skip
                logger.info("Chat %s has empty base title, skipping title update", chat_id)
                return
            await set_chat_title_safely(chat_id, base_title, streak)

    await asyncio.gather(*(update_title(c, s) for c, s in tasks))
    logger.info("Daily process finished for %d chats", len(tasks))


# ---------------- STARTUP / SCHEDULER ----------------
async def on_startup(_):
    load_data()
    # start scheduler
    scheduler = AsyncIOScheduler(timezone=TZ)
    # run at 00:00 daily in TZ
    scheduler.add_job(daily_process, "cron", hour=0, minute=0)
    scheduler.start()
    logger.info("Scheduler started (daily job at 00:00 %s)", TZ)


async def on_shutdown(_):
    await bot.close()
    logger.info("Bot stopped")


if __name__ == "__main__":
    # Register commands (optional, improves UX)
    async def set_commands():
        await bot.set_my_commands([
            types.BotCommand("streak", "Показать текущий стрик"),
            types.BotCommand("set", "Установить стрик вручную: /set <число>"),
            types.BotCommand("reset", "Сбросить стрик")
        ])

    loop = asyncio.get_event_loop()
    loop.run_until_complete(set_commands())
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)