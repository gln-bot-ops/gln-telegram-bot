"""User-facing handlers: start/referrals, mining, upgrades, leaderboard."""
import logging
import time

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

from . import config, db, game, texts

router = Router()

# --- Simple in-memory throttle: max one action per user per second (anti-spam).
_last_action: dict[int, float] = {}


def _throttled(user_id: int) -> bool:
    now = time.monotonic()
    if now - _last_action.get(user_id, 0) < 1.0:
        return True
    _last_action[user_id] = now
    return False


MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⛏️ التعدين"), KeyboardButton(text="💰 رصيدي")],
        [KeyboardButton(text="🛒 الترقيات"), KeyboardButton(text="🏆 المتصدرين")],
        [KeyboardButton(text="👥 ادعُ أصحابك")],
    ],
    resize_keyboard=True,
)


# Deals-channel promo: one quiet row under key screens, never blocks play.
DEALS_BTN = InlineKeyboardButton(
    text="🎁 عروض ولقط اليومية", url=config.DEALS_CHANNEL_URL
)

JOIN_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎁 انضم لقناة العروض", url=config.DEALS_CHANNEL_URL)],
    [InlineKeyboardButton(text="انضميت ✅", callback_data="join:check")],
])


async def _is_deals_member(bot, user_id: int) -> bool:
    """Force-join check for /start. Fail open on anything ambiguous so no
    player is ever locked out wrongly; only a definitive non-member is gated.
    Telegram raises "member not found" (or "user not found") for users who
    never joined the channel - that case IS a definitive non-member."""
    log = logging.getLogger(__name__)
    try:
        member = await bot.get_chat_member(config.DEALS_CHAT_ID, user_id)
    except Exception as exc:
        if "not found" in str(exc).lower():
            return False
        log.warning("deals membership check failed open for %s: %s", user_id, exc)
        return True
    status = getattr(member, "status", "")
    if status == "restricted":
        return bool(getattr(member, "is_member", True))
    return status not in ("left", "kicked")


def _mine_kb(session, now: float):
    if not session:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⛏️ ابدأ التعدين", callback_data="mine:start")],
            [DEALS_BTN],
        ])
    if now >= session["ready_at"]:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 اسحب النقاط", callback_data="mine:claim")],
            [DEALS_BTN],
        ])
    return None


def _mine_text(user, session, now: float) -> str:
    if not session:
        return texts.MINE_IDLE.format(
            cooldown=game.fmt_duration(game.cooldown_sec(user["cooldown_level"])),
            amount=game.session_amount(user["rig_level"]),
        )
    if now >= session["ready_at"]:
        return texts.MINE_READY.format(
            amount=session["amount"], grace=game.fmt_duration(game.GRACE_SEC)
        )
    return texts.MINE_RUNNING.format(
        left=game.fmt_duration(session["ready_at"] - now), amount=session["amount"]
    )


async def _notify_inviter(bot, inviter_id: int, text: str):
    try:
        await bot.send_message(inviter_id, text)
    except Exception:
        pass  # inviter blocked the bot; nothing to do


async def _start_flow(bot, tg_user, ref_code):
    """The normal /start path once channel membership is confirmed."""
    user, created, inviter = db.register_user(
        tg_user.id, tg_user.username, tg_user.first_name, ref_code
    )
    text = texts.WELCOME.format(points=user["points"], ref_code=user["ref_code"])
    if created and inviter:
        text += texts.WELCOME_REFERRED
        await _notify_inviter(bot, inviter, texts.INVITER_NOTIFY_JOIN.format(bonus=game.REF_JOIN_BONUS))
    return text


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject):
    ref_code = None
    if command.args and command.args.startswith("ref_"):
        ref_code = command.args[4:]
    if not await _is_deals_member(message.bot, message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 انضم لقناة العروض", url=config.DEALS_CHANNEL_URL)],
            [InlineKeyboardButton(
                text="انضميت ✅",
                callback_data=("join:check:" + ref_code)[:64] if ref_code else "join:check",
            )],
        ])
        await message.answer(texts.JOIN_REQUIRED, reply_markup=kb)
        return
    text = await _start_flow(message.bot, message.from_user, ref_code)
    await message.answer(text, reply_markup=MAIN_KB)


@router.callback_query(F.data.startswith("join:check"))
async def on_join_check(cb: CallbackQuery):
    if not await _is_deals_member(cb.bot, cb.from_user.id):
        await cb.answer(texts.JOIN_STILL_NOT_MEMBER, show_alert=True)
        return
    ref_code = cb.data.partition("join:check:")[2] or None
    await cb.answer(texts.JOIN_CONFIRMED)
    text = await _start_flow(cb.bot, cb.from_user, ref_code)
    await cb.message.answer(text, reply_markup=MAIN_KB)


@router.message(F.text == "⛏️ التعدين")
async def on_mine(message: Message):
    if _throttled(message.from_user.id):
        return
    user = db.get_user(message.from_user.id)
    session = db.get_active_session(user["id"])
    now = time.time()
    await message.answer(_mine_text(user, session, now), reply_markup=_mine_kb(session, now))


@router.callback_query(F.data == "mine:start")
async def on_mine_start(cb: CallbackQuery):
    user = db.get_user(cb.from_user.id)
    session, err = db.start_session(user["id"])
    if err:
        await cb.answer("عندك جلسة شغالة بالفعل!", show_alert=True)
        return
    await cb.message.edit_text(texts.MINE_STARTED.format(
        cooldown=game.fmt_duration(session["ready_at"] - session["started_at"]),
        amount=session["amount"],
        grace=game.fmt_duration(game.GRACE_SEC),
    ))
    await cb.answer()


@router.callback_query(F.data == "mine:claim")
async def on_mine_claim(cb: CallbackQuery):
    result, err = db.claim_session(cb.from_user.id)
    if err == "no_session":
        await cb.answer(texts.CLAIM_NONE, show_alert=True)
        return
    if err == "too_early":
        await cb.answer(texts.CLAIM_TOO_EARLY.format(
            left=game.fmt_duration(result["seconds_left"])), show_alert=True)
        return
    await cb.message.edit_text(texts.CLAIMED.format(
        amount=result["amount"], balance=result["new_balance"]))
    if result["first_claim"] and result["inviter"]:
        await _notify_inviter(cb.bot, result["inviter"],
                              texts.INVITER_NOTIFY_FIRST_CLAIM.format(bonus=game.REF_FIRST_CLAIM_BONUS))
    await cb.answer()


@router.message(F.text == "💰 رصيدي")
async def on_balance(message: Message):
    user = db.get_user(message.from_user.id)
    await message.answer(texts.BALANCE.format(
        points=user["points"], rig=user["rig_level"],
        rate=game.session_amount(user["rig_level"]),
        cd=user["cooldown_level"],
        cooldown=game.fmt_duration(game.cooldown_sec(user["cooldown_level"])),
        refs=db.referral_count(user["id"]),
    ))


def _upgrades_text(user) -> str:
    return texts.UPGRADES_MENU.format(
        rig=user["rig_level"],
        rate=game.session_amount(user["rig_level"]),
        rate_next=game.session_amount(user["rig_level"] + 1),
        rig_cost=game.upgrade_cost(user["rig_level"]),
        cd=user["cooldown_level"],
        cooldown=game.fmt_duration(game.cooldown_sec(user["cooldown_level"])),
        cooldown_next=game.fmt_duration(game.cooldown_sec(user["cooldown_level"] + 1)),
        cd_cost=game.upgrade_cost(user["cooldown_level"]),
        points=user["points"],
    )


def _upgrades_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏️ رقّي المعدّة", callback_data="up:rig")],
        [InlineKeyboardButton(text="⏱️ رقّي السرعة", callback_data="up:cooldown")],
        [DEALS_BTN],
    ])


@router.message(F.text == "🛒 الترقيات")
async def on_upgrades(message: Message):
    user = db.get_user(message.from_user.id)
    await message.answer(_upgrades_text(user), reply_markup=_upgrades_kb())


@router.callback_query(F.data.in_({"up:rig", "up:cooldown"}))
async def on_upgrade_buy(cb: CallbackQuery):
    kind = "rig" if cb.data == "up:rig" else "cooldown"
    new_level, err = db.buy_upgrade(cb.from_user.id, kind)
    if err:
        await cb.answer(texts.UPGRADE_NO_POINTS, show_alert=True)
        return
    what = "المعدّة" if kind == "rig" else "السرعة"
    await cb.answer(texts.UPGRADE_DONE.format(what=what, level=new_level), show_alert=True)
    user = db.get_user(cb.from_user.id)
    await cb.message.edit_text(_upgrades_text(user), reply_markup=_upgrades_kb())


@router.message(F.text == "🏆 المتصدرين")
async def on_leaderboard(message: Message):
    rows = db.leaderboard(10)
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    text = texts.LEADERBOARD_TITLE
    for i, r in enumerate(rows):
        name = r["first_name"] or (f"@{r['username']}" if r["username"] else "معدّن")
        text += texts.LEADERBOARD_ROW.format(medal=medals[i], name=name, points=r["total_earned"])
    await message.answer(text)


@router.message(F.text == "👥 ادعُ أصحابك")
async def on_referral(message: Message):
    user = db.get_user(message.from_user.id)
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user['ref_code']}"
    await message.answer(texts.REFERRAL.format(
        join_bonus=game.REF_JOIN_BONUS,
        claim_bonus=game.REF_FIRST_CLAIM_BONUS,
        link=link,
        refs=db.referral_count(user["id"]),
    ))
