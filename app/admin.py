"""Admin-only commands: /stats and /broadcast. ADMIN_IDS come from config."""
import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from . import db, texts
from .config import ADMIN_IDS

router = Router()


def _is_admin(message: Message) -> bool:
    return bool(ADMIN_IDS) and message.from_user.id in ADMIN_IDS


@router.message(Command("stats"))
async def on_stats(message: Message):
    if not _is_admin(message):
        await message.answer(texts.ADMIN_ONLY)
        return
    await message.answer(texts.ADMIN_STATS.format(**db.stats()))


@router.message(Command("broadcast"), F.text)
async def on_broadcast(message: Message):
    if not _is_admin(message):
        await message.answer(texts.ADMIN_ONLY)
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        await message.answer(texts.BROADCAST_USAGE)
        return
    ok, fail = 0, 0
    for uid in db.all_user_ids():
        try:
            await message.bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # stay under Telegram flood limits
    await message.answer(texts.BROADCAST_DONE.format(ok=ok, fail=fail))
