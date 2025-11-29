import asyncio
import json
from datetime import datetime, time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = "PUT_YOUR_TOKEN"
DATA_FILE = Path("data.json")

bot = Bot(TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

def load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {}

def save_data(data):
    DATA_FILE.write_text(json.dumps(data))

data = load_data()

@dp.message()
async def track(message: Message):
    if message.chat.type not in ("group","supergroup"):
        return
    cid = str(message.chat.id)
    today = datetime.utcnow().date().isoformat()
    info = data.get(cid, {"streak": 0, "last_day": None, "active_today": False})
    info["active_today"] = True
    data[cid] = info
    save_data(data)

@dp.message(Command("streak"))
async def cmd_streak(message: Message):
    cid = str(message.chat.id)
    info = data.get(cid, {"streak":0})
    await message.reply(f"🔥 Стрик: {info['streak']}")

@dp.message(Command("set"))
async def cmd_set(message: Message):
    if not message.from_user or not message.from_user.id:
        return
    parts = message.text.split()
    if len(parts)!=2 or not parts[1].isdigit():
        return await message.reply("Использование: /set 10")
    cid=str(message.chat.id)
    data.setdefault(cid,{"streak":0,"active_today":False,"last_day":None})
    data[cid]["streak"]=int(parts[1])
    save_data(data)
    await message.reply("Установлено.")

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    cid=str(message.chat.id)
    if cid in data:
        data[cid]["streak"]=0
        save_data(data)
    await message.reply("Стрик сброшен.")

async def daily_update():
    now = datetime.utcnow().date().isoformat()
    for cid, info in data.items():
        if info.get("active_today"):
            info["streak"] = info.get("streak",0)+1
        else:
            info["streak"] = 0
        info["active_today"] = False
        data[cid] = info
        try:
            await bot.set_chat_title(int(cid), f"🔥 {info['streak']}")
        except:
            pass
    save_data(data)

async def main():
    scheduler.add_job(daily_update, "cron", hour=0, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
