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
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ===== CONFIG =====
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    raise RuntimeError('BOT_TOKEN env var is required (set it in Railway Variables)')
DATA_FILE = os.environ.get('DATA_FILE', 'data.json')
TZ = os.environ.get('TZ', 'Europe/Kyiv')

# Emoji choices
GRAY_HEART = '🩶'   # waiting state
RED_HEART = '❤️'   # active state

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# initialize bot correctly for aiogram 3.7+
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)
data_lock = asyncio.Lock()

# Data schema (in JSON):
# {
#   "<chat_id>": {
#       "streak": int,
#       "waiting": bool,          # True after 00:01 until first message
#       "active_today": bool,     # True if at least one user message today
#       "original_title": str or None,
#       "last_updated": "YYYY-MM-DD" or None
#   }
# }

def atomic_write(path: str, content: str):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.replace(tmp, path)

async def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.exception('Failed to load data.json, starting with empty data')
        return {}

async def save_data(data: Dict[str, Any]):
    async with data_lock:
        atomic_write(DATA_FILE, json.dumps(data, ensure_ascii=False, indent=2))

def strip_streak_suffix(title: str) -> str:
    if not title:
        return ''
    return re.sub(r'\s*\d+\s*(?:' + re.escape(GRAY_HEART) + r'|' + re.escape(RED_HEART) + r')\s*$', '', title).strip()

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False

async def ensure_entry(data: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
    cid = str(chat_id)
    if cid not in data:
        data[cid] = {
            'streak': 0,
            'waiting': False,
            'active_today': False,
            'original_title': None,
            'last_updated': None
        }
    return data[cid]

async def set_chat_title_safe(chat_id: int, base_title: str, streak: int, heart: str):
    if not base_title and streak==0:
        return
    new_title = f"{base_title} {streak}{heart}" if streak > 0 else base_title
    try:
        await bot.set_chat_title(chat_id, new_title)
    except Exception:
        logger.exception('Failed to set chat title for %s', chat_id)

# ===== Commands =====
@dp.message(Command('help'))
async def cmd_help(message: types.Message):
    await message.reply(
        'Команды:\n'
        '/streak — показать текущий стрик и состояние\n'
        '/set <число> — (админ) установить стрик\n'
        '/reset — (админ) обнулить стрик\n'
        '/status — (админ) подробная информация по группе\n'
        '/debug — (админ) показать внутренние данные\n'
        '/force_tick — (админ) принудительно выполнить 00:01 тик\n'
        '/rename — (админ) обновить название группы по текущим данным\n'
    )

@dp.message(Command('streak'))
async def cmd_streak(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply('Команда доступна только в группах.')
    data = await load_data()
    entry = await ensure_entry(data, message.chat.id)
    heart = GRAY_HEART if entry.get('waiting') else (RED_HEART if entry.get('streak', 0) > 0 else '')
    await message.reply(f"Текущий стрик: {entry.get('streak',0)}{heart}")

@dp.message(Command('set'))
async def cmd_set(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply('Только в группах.')
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply('Соси лапу не достойный')
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.reply('Использование: /set <число>')
    val = int(parts[1])
    data = await load_data()
    entry = await ensure_entry(data, message.chat.id)
    entry['streak'] = val
    entry['waiting'] = False
    entry['active_today'] = False
    # capture base title
    try:
        chat = await bot.get_chat(message.chat.id)
        base = strip_streak_suffix(chat.title or '')
        entry['original_title'] = base
        await set_chat_title_safe(message.chat.id, base, val, RED_HEART if val>0 else '')
    except Exception:
        logger.exception('Failed to set title on /set')
    await save_data(data)
    await message.reply(f'Стрик установлен: {val}')

@dp.message(Command('reset'))
async def cmd_reset(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply('Только в группах.')
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply('Только админам.')
    data = await load_data()
    entry = await ensure_entry(data, message.chat.id)
    entry['streak'] = 0
    entry['waiting'] = False
    entry['active_today'] = False
    try:
        chat = await bot.get_chat(message.chat.id)
        base = entry.get('original_title') or strip_streak_suffix(chat.title or '')
        entry['original_title'] = base
        await set_chat_title_safe(message.chat.id, base, 0, '')
    except Exception:
        logger.exception('Failed to restore title on /reset')
    await save_data(data)
    await message.reply('Стрик обнулён.')

@dp.message(Command('status'))
async def cmd_status(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await message.reply('Только в группах.')
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply('Только админам.')
    data = await load_data()
    entry = data.get(str(message.chat.id), {})
    await message.reply(f"Status:\n{json.dumps(entry, ensure_ascii=False, indent=2)}")

@dp.message(Command('debug'))
async def cmd_debug(message: types.Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply('Только админам.')
    data = await load_data()
    await message.reply(f"DATA (global): {json.dumps(data, ensure_ascii=False)[:4000]}")

@dp.message(Command('force_tick'))
async def cmd_force_tick(message: types.Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply('Только админам.')
    await run_tick_start_of_day()
    await message.reply('Принудительный 00:01 тик выполнен.')

@dp.message(Command('rename'))
async def cmd_rename(message: types.Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply('Только админам.')
    data = await load_data()
    entry = await ensure_entry(data, message.chat.id)
    try:
        chat = await bot.get_chat(message.chat.id)
        base = entry.get('original_title') or strip_streak_suffix(chat.title or '')
        entry['original_title'] = base
        heart = GRAY_HEART if entry.get('waiting') else (RED_HEART if entry.get('streak',0)>0 else '')
        await set_chat_title_safe(message.chat.id, base, entry.get('streak',0), heart)
        await save_data(data)
        await message.reply('Название обновлено по текущему стрику.')
    except Exception:
        await message.reply('Не удалось обновить название.')

# ===== Message handler =====
@dp.message()
async def handle_message(message: types.Message):
    # only groups
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    # delete service messages and ignore them for activity
    if message.new_chat_title or message.new_chat_photo or message.new_chat_members or message.left_chat_member or message.pinned_message:
        data = await load_data()
        if data.get('delete_enabled', True):
            try:
                await message.delete()
            except Exception:
                pass
        return
    # ignore bot messages
    if message.from_user and message.from_user.is_bot:
        return
    data = await load_data()
    cid = str(message.chat.id)
    entry = await ensure_entry(data, message.chat.id)
    # first user message during waiting -> increment and set red heart
    if entry.get('waiting'):
        entry['streak'] = int(entry.get('streak', 0)) + 1
        entry['waiting'] = False
        entry['active_today'] = True
        try:
            chat = await bot.get_chat(int(cid))
            base = entry.get('original_title') or strip_streak_suffix(chat.title or '')
            entry['original_title'] = base
            await set_chat_title_safe(int(cid), base, entry['streak'], RED_HEART)
        except Exception:
            logger.exception('Failed to update title on first activity of the day')
    else:
        entry['active_today'] = True
    data[cid] = entry
    await save_data(data)

# ===== Scheduled jobs =====
async def run_tick_start_of_day():
    """Run at 00:01 in TZ: prepare waiting state and show gray heart"""
    tz = pytz.timezone(TZ)
    today = datetime.now(tz).date().isoformat()
    data = await load_data()
    changed = False
    for cid, entry in list(data.items()):
        entry = await ensure_entry(data, int(cid))
        entry['waiting'] = True
        entry['active_today'] = False
        try:
            chat = await bot.get_chat(int(cid))
            base = entry.get('original_title') or strip_streak_suffix(chat.title or '')
            entry['original_title'] = base
            await set_chat_title_safe(int(cid), base, entry.get('streak',0), GRAY_HEART if entry.get('streak',0)>0 else '')
        except Exception:
            logger.exception('Failed updating title at start_of_day for %s', cid)
        data[cid] = entry
        changed = True
    if changed:
        await save_data(data)

async def run_tick_end_of_day():
    """Run at 23:59 in TZ: finalize day — if still waiting and no activity, reset streak"""
    tz = pytz.timezone(TZ)
    today = datetime.now(tz).date().isoformat()
    data = await load_data()
    changed = False
    for cid, entry in list(data.items()):
        entry = await ensure_entry(data, int(cid))
        if entry.get('waiting') and not entry.get('active_today'):
            entry['streak'] = 0
            entry['waiting'] = False
            entry['active_today'] = False
            try:
                chat = await bot.get_chat(int(cid))
                base = entry.get('original_title') or strip_streak_suffix(chat.title or '')
                entry['original_title'] = base
                await set_chat_title_safe(int(cid), base, 0, '')
            except Exception:
                logger.exception('Failed restoring title at end_of_day for %s', cid)
            data[cid] = entry
            changed = True
        else:
            entry['active_today'] = False
            data[cid] = entry
    if changed:
        await save_data(data)

async def on_startup():
    scheduler.add_job(run_tick_start_of_day, 'cron', hour=0, minute=1)
    scheduler.add_job(run_tick_end_of_day, 'cron', hour=23, minute=59)
    scheduler.start()
    logger.info('Scheduler started (00:01 start, 23:59 end) TZ=%s', TZ)

async def main():
    await on_startup()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
