
import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ContentType, ChatType
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

TOKEN = "YOUR_TOKEN"

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

DATA_FILE = Path("data.json")

if not DATA_FILE.exists():
    DATA_FILE.write_text(json.dumps({"groups": {}, "delete_enabled": True}, indent=2))

def load_data():
    return json.loads(DATA_FILE.read_text())

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))

@dp.message(Command("toggle_deletes"))
async def toggle(msg: types.Message):
    data = load_data()
    data["delete_enabled"] = not data["delete_enabled"]
    save_data(data)
    await msg.answer("Авто-удаление: включено" if data["delete_enabled"] else "Авто-удаление: выключено")

@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(
        "<b>Команды:</b>\n"
        "/help — список команд\n"
        "/streak — текущий стрик\n"
        "/set X — задать стрик\n"
        "/reset — сброс стрика\n"
        "/toggle_deletes — включить/выключить автоудаление системных сообщений\n"
    )

@dp.message(Command("streak"))
async def cmd_streak(msg: types.Message):
    data = load_data()["groups"].get(str(msg.chat.id), {})
    await msg.answer(f"Текущий стрик: <b>{data.get('streak',0)}</b>")

@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    data = load_data()
    gid = str(msg.chat.id)
    if gid not in data["groups"]:
        data["groups"][gid] = {"streak":0,"active_today":False,"last_date":None}
    data["groups"][gid]["streak"] = 0
    save_data(data)
    await msg.answer("Стрик сброшен.")

@dp.message(Command("set"))
async def cmd_set(msg: types.Message):
    parts = msg.text.split()
    if len(parts)!=2 or not parts[1].isdigit():
        return await msg.answer("Использование: /set 10")
    val = int(parts[1])
    data = load_data()
    gid = str(msg.chat.id)
    if gid not in data["groups"]:
        data["groups"][gid]={"streak":0,"active_today":False,"last_date":None}
    data["groups"][gid]["streak"]=val
    save_data(data)
    await msg.answer(f"Стрик установлен: {val}")

@dp.message()
async def activity(msg: types.Message):
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    data = load_data()
    gid = str(msg.chat.id)
    if gid not in data["groups"]:
        data["groups"][gid] = {
            "streak":0,
            "active_today":True,
            "last_date": datetime.now(timezone.utc).date().isoformat()
        }
    else:
        data["groups"][gid]["active_today"] = True
    save_data(data)

async def daily_update():
    data = load_data()
    today = datetime.now(timezone.utc).date().isoformat()
    for gid,g in data["groups"].items():
        last = g.get("last_date")
        active = g.get("active_today",False)
        if last!=today:
            if active:
                g["streak"] += 1
            else:
                g["streak"] = 0
            g["active_today"] = False
            g["last_date"] = today
            try:
                await bot.set_chat_title(int(gid), f"❤️ {g['streak']}")
            except Exception as e:
                logging.error(e)
    save_data(data)

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
    if not data.get("delete_enabled",True): return
    try: await msg.delete()
    except: pass

async def start_scheduler():
    sch = AsyncIOScheduler()
    sch.add_job(daily_update, CronTrigger(hour=0, minute=1))
    sch.start()

async def main():
    await start_scheduler()
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
