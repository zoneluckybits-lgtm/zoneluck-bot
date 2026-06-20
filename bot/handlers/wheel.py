import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import get_user_by_telegram_id, get_user_lang

SPIN_COST = 5.0

# (emoji, multiplier, label, weight)
PRIZES = [
    ("💀", 0,   "خسارة! حظك أحسن المرة الجاية 😔",  60),
    ("🍀", 1,   "استرداد المبلغ! تعادل 🍀",           20),
    ("⭐", 2,   "ضعفين! ×2 🌟",                        5),
    ("💰", 5,   "خمسة أضعاف! ×5 💰",                   4),
    ("💎", 10,  "عشرة أضعاف! ×10 💎",                  2),
    ("🔥", 20,  "جاكبوت! ×20 🔥🎉",                    1),
]

SYMBOLS = [p[0] for p in PRIZES]
_BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]])


def _pick_prize():
    weights = [p[3] for p in PRIZES]
    return random.choices(PRIZES, weights=weights, k=1)[0]


def _spin_row(offset: int) -> str:
    rotated = SYMBOLS[offset % len(SYMBOLS):] + SYMBOLS[:offset % len(SYMBOLS)]
    return "  ".join(rotated)


async def wheel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    prizes_lines = "\n".join(
        f"  {emoji}  {'خسارة' if mult == 0 else f'ربح ${SPIN_COST * mult:.0f}'}"
        for emoji, mult, _, _ in PRIZES
    )

    text = (
        f"🎡 *دولاب الحظ*\n\n"
        f"💰 رصيدك: *${db_user['balance']:.2f}*\n"
        f"💵 سعر الدورة الواحدة: *${SPIN_COST:.0f}*\n\n"
        f"🏆 *الجوائز الممكنة:*\n"
        f"{prizes_lines}\n\n"
        f"_جرّب حظك! 🤞_"
    )

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎡  دوّر!", callback_data="wheel_spin")],
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
        ]),
    )


async def wheel_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < SPIN_COST:
        await query.edit_message_text(
            f"❌ *رصيدك غير كافٍ!*\n\n"
            f"💰 رصيدك الحالي: *${db_user['balance']:.2f}*\n"
            f"💵 سعر الدورة: *${SPIN_COST:.0f}*\n\n"
            f"أودع أولاً ثم جرّب حظك! 💳",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 إيداع", callback_data="wallet")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
            ]),
        )
        return

    prize_emoji, prize_mult, prize_label, _ = _pick_prize()
    prize_amount = SPIN_COST * prize_mult

    with db() as conn:
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE telegram_id = ?",
            (SPIN_COST, user.id),
        )
        if prize_amount > 0:
            conn.execute(
                "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
                (prize_amount, user.id),
            )
        conn.execute(
            """INSERT INTO wheel_spins (user_id, cost, prize_emoji, prize_mult, prize_amount)
               VALUES (?, ?, ?, ?, ?)""",
            (db_user["id"], SPIN_COST, prize_emoji, prize_mult, prize_amount),
        )

    # ── Animation ──
    # Fast frames
    fast_delays  = [0.35, 0.35, 0.40, 0.40, 0.45]
    slow_delays  = [0.60, 0.85, 1.10]

    for i, delay in enumerate(fast_delays):
        row = _spin_row(i)
        try:
            await query.edit_message_text(
                f"🎡 *دولاب الحظ*\n\n🎰 جاري الدوران...\n\n{row}",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await asyncio.sleep(delay)

    for i, delay in enumerate(slow_delays):
        row = _spin_row(len(fast_delays) + i)
        try:
            await query.edit_message_text(
                f"🎡 *دولاب الحظ*\n\n⏳ يتباطأ...\n\n{row}",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await asyncio.sleep(delay)

    # ── Final result ──
    new_balance = db_user["balance"] - SPIN_COST + prize_amount

    if prize_mult == 0:
        result = (
            f"🎡 *دولاب الحظ*\n\n"
            f"🎯 توقّف على:\n\n"
            f"      {prize_emoji}\n\n"
            f"😔 *{prize_label}*\n\n"
            f"💰 رصيدك الجديد: *${new_balance:.2f}*"
        )
    else:
        result = (
            f"🎡 *دولاب الحظ*\n\n"
            f"🎯 توقّف على:\n\n"
            f"      {prize_emoji}\n\n"
            f"🎉 *{prize_label}*\n"
            f"ربحت *${prize_amount:.2f}*! 🎊\n\n"
            f"💰 رصيدك الجديد: *${new_balance:.2f}*"
        )

    try:
        await query.edit_message_text(
            result,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎡  دوّر مجدداً!", callback_data="wheel_spin")],
                [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
            ]),
        )
    except Exception:
        pass
