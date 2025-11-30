
import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ContentType, ChatType

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

TOKEN = "8501817032:AAHK4DpmF4CISTfsTJpb0MzXkeInRDA9SU8"

bot = Bot(TOKEN, parse_mode="HTML")
dp = Dispatcher()

DATA_FILE = Path("data.json")

if not DATA_FILE.exists():
    DATA_FILE.write_text(json.dumps({"groups": {}, "delete_enabled": True}, indent=2))

def load_data():
    return json.loads(DATA_FILE.read_text())

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))

# ----------------------------------------------------------
# Locales
# ----------------------------------------------------------
LOCALES = {
    "ru": {
        "help": (
            "<b>Команды бота:</b>\n"
            "/help — список команд\n"
            "/streak — показать стрик\n"
            "/set X — установить стрик\n"
            "/reset — сбросить стрик\n"
            "/toggle_deletes — включить/выключить автудаление сервисных сообщений\n"
        ),
        "deletes_on": "Авто‑удаление сервисных сообщений: <b>включено</b>",
        "deletes_off": "Авто‑удаление сервисных сообщений: <b>выключено</b>",
    },
    "ua": {
        "help": (
            "<b>Команди бота:</b>\n"
            "/help — список команд\n"
            "/streak — показати стрик\n"
            "/set X — встановити стрик\n"
            "/reset — скинути стрик\n"
            "/toggle_deletes — увімкнути/вимкнути авто‑видалення сервісних повідомлень\n"
        ),
        "deletes_on": "Авто‑видалення сервісних повідомлень: <b>увімкнено</b>",
        "deletes_off": "Авто‑видалення сервісних повідомлень: <b>вимкнено</b>",
    },
    "en": {
        "help": (
            "<b>Bot commands:</b>\n"
            "/help — list commands\n"
            "/streak — show streak\n"
            "/set X — set streak\n"
            "/reset — reset streak\n"
            "/toggle_deletes — enable/disable service message auto-delete\n"
        ),
        "deletes_on": "Service auto-delete: <b>enabled</b>",
        "deletes_off": "Service auto-delete: <b>disabled</b>",
    }
}

def get_locale(chat_id):
    data = load_data()
    groups = data["groups"]
    if str(chat_id) not in groups:
        groups[str(chat_id)] = {
            "streak": 0,
            "active_today": False,
            "last_date": None,
            "lang": "ru",
        }
        save_data(data)
    return groups[str(chat_id)]["lang"]

def t(chat_id, key):
    lang = get_locale(chat_id)
    return LOCALES.get(lang, LOCALES["ru"]).get(key, "")

# ----------------------------------------------------------
# Service delete toggle
# ----------------------------------------------------------
@dp.message(Command("toggle_deletes"))
async def toggle(msg: types.Message):
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await msg.answer("Команда только для групп.")

    data = load_data()
    data["delete_enabled"] = not data["delete_enabled"]
    save_data(data)

    await msg.answer(
        t(msg.chat.id, "deletes_on") if data["delete_enabled"] else t(msg.chat.id, "deletes_off")
    )

# ----------------------------------------------------------
# Help
# ----------------------------------------------------------
@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(t(msg.chat.id, "help"))

# ----------------------------------------------------------
# Streak commands
# ----------------------------------------------------------
@dp.message(Command("streak"))
async def cmd_streak(msg: types.Message):
    data = load_data()["groups"].get(str(msg.chat.id), {})
    streak = data.get("streak", 0)
    await msg.answer(f"Текущий стрик: <b>{streak}</b>")

@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    data = load_data()
    data["groups"][str(msg.chat.id)]["streak"] = 0
    data["groups"][str(msg.chat.id)]["active_today"] = False
    save_data(data)
    await msg.answer("Стрик сброшен.")

@dp.message(Command("set"))
async def cmd_set(msg: types.Message):
    parts = msg.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await msg.answer("Использование: /set 10")

    value = int(parts[1])
    data = load_data()
    data["groups"][str(msg.chat.id)]["streak"] = value
    save_data(data)
    await msg.answer(f"Стрик установлен на {value}")

# ----------------------------------------------------------
# Detect activity
# ----------------------------------------------------------
@dp.message()
async def any_message(msg: types.Message):
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    data = load_data()
    groups = data["groups"]
    gid = str(msg.chat.id)

    if gid not in groups:
        groups[gid] = {
            "streak": 0,
            "active_today": True,
            "last_date": datetime.now(timezone.utc).date().isoformat(),
            "lang": "ru",
        }
    else:
        groups[gid]["active_today"] = True

    save_data(data)

# ----------------------------------------------------------
# Daily update
# ----------------------------------------------------------
async def daily_update():
    data = load_data()
    groups = data["groups"]

    today = datetime.now(timezone.utc).date().isoformat()

    for gid, g in groups.items():
        last = g.get("last_date")
        active = g.get("active_today", False)

        if last != today:
            if active:
                g["streak"] += 1
            else:
                g["streak"] = 0

            g["active_today"] = False
            g["last_date"] = today

            # update group title
            try:
                new_title = f"🔥 {g['streak']}"
                await bot.set_chat_title(int(gid), new_title)
            except Exception as e:
                logging.error(f"Title update error {gid}: {e}")

    save_data(data)

# ----------------------------------------------------------
# Delete service messages
# ----------------------------------------------------------
SERVICE_TYPES = {
    ContentType.NEW_CHAT_TITLE,
    ContentType.NEW_CHAT_PHOTO,
    ContentType.DELETE_CHAT_PHOTO,
    ContentType.LEFT_CHAT_MEMBER,
    ContentType.NEW_CHAT_MEMBERS,
    ContentType.PINNED_MESSAGE,
}

@dp.message(content_types=SERVICE_TYPES)
async def delete_service(msg: types.Message):
    data = load_data()
    if not data.get("delete_enabled", True):
        return

    try:
        await msg.delete()
    except:
        pass

# ----------------------------------------------------------
# Scheduler
# ----------------------------------------------------------
async def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_update, CronTrigger(hour=0, minute=1))
    scheduler.start()

# ----------------------------------------------------------
# Start
# ----------------------------------------------------------
async def main():
    await start_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
