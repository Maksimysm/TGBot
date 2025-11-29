import asyncio
import json
from datetime import datetime, timezone, time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ChatType
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = "8501817032:AAHK4DpmF4CISTfsTJpb0MzXkeInRDA9SU8"

DATA_FILE = Path("data.json")

def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

bot = Bot(TOKEN)
dp = Dispatcher()

async def ensure_group_entry(chat_id):
    if str(chat_id) not in data:
        data[str(chat_id)] = {
            "streak": 0,
            "active_today": False,
        }
        save_data(data)

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def track_message(msg: Message):
    cid = str(msg.chat.id)
    await ensure_group_entry(cid)
    data[cid]["active_today"] = True
    save_data(data)

async def update_streaks():
    today = datetime.now(timezone.utc).date().isoformat()

    for cid, info in data.items():
        if info.get("active_today"):
            info["streak"] += 1
        else:
            info["streak"] = 0

        info["active_today"] = False

        try:
            await bot.set_chat_title(
                int(cid),
                f"{cid} {info['streak']}🔥"
            )
        except Exception:
            pass

    save_data(data)

@dp.message(Command("streak"))
async def cmd_streak(msg: Message):
    cid = str(msg.chat.id)
    await ensure_group_entry(cid)
    await msg.answer(f"Current streak: {data[cid]['streak']}🔥")

@dp.message(Command("set"))
async def cmd_set(msg: Message):
    cid = str(msg.chat.id)
    await ensure_group_entry(cid)

    parts = msg.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await msg.answer("Usage: /set <number>")

    data[cid]["streak"] = int(parts[1])
    save_data(data)
    await msg.answer("Streak updated.")

@dp.message(Command("reset"))
async def cmd_reset(msg: Message):
    cid = str(msg.chat.id)
    await ensure_group_entry(cid)
    data[cid]["streak"] = 0
    data[cid]["active_today"] = False
    save_data(data)
    await msg.answer("Streak reset.")

async def main():
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(update_streaks, "cron", hour=0, minute=0)
    scheduler.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
