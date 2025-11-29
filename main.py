import asyncio
import os
from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = os.getenv("TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Загружаем streak из файла
try:
    with open("streak.txt", "r") as f:
        streak = int(f.read().strip())
except:
    streak = 1

async def update_group_title():
    global streak
    streak += 1
    new_title = f"МММ {streak}🔥"

    try:
        await bot.set_chat_title(chat_id=GROUP_ID, title=new_title)
    except Exception as e:
        print("Error updating title:", e)

    # Сохраняем
    with open("streak.txt", "w") as f:
        f.write(str(streak))


async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(update_group_title, "cron", hour=10)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())