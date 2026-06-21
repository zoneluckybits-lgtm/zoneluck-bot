import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import register_user, get_user_by_telegram_id, format_user_name, get_user_lang, set_user_lang
from lang import t

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))


def is_admin(telegram_id):
    return telegram_id == ADMIN_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referred_by = None
    args = context.args or []
    if args and args[0].startswith("ref_"):
        try:
            referred_by = int(args[0][4:])
            if referred_by == user.id:
                referred_by = None  # لا يحيل نفسه
        except ValueError:
            pass

    try:
        register_user(user.id, user.username, user.full_name, referred_by)
    except Exception:
        pass  # إذا كان المستخدم مسجلاً مسبقاً أو حدث خطأ، نكمل

    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    if not db_user:
        # محاولة أخيرة لتسجيله
        try:
            register_user(user.id, user.username, user.full_name, None)
            db_user = get_user_by_telegram_id(user.id)
        except Exception:
            pass

    if not db_user:
        await update.message.reply_text("❌ حدث خطأ. حاول مجدداً /start")
        return

    name = format_user_name(dict(db_user))
    await update.message.reply_text(
        t("welcome", lang, name=name, balance=db_user["balance"]),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user.id, lang),
    )


def main_menu_keyboard(telegram_id, lang="ar"):
    buttons = [
        [
            InlineKeyboardButton(t("btn_wallet", lang), callback_data="wallet"),
            InlineKeyboardButton(t("btn_matches", lang), callback_data="matches_menu"),
        ],
        [
            InlineKeyboardButton(t("btn_lottery", lang), callback_data="lottery_menu"),
            InlineKeyboardButton(t("btn_referral", lang), callback_data="referral"),
        ],
        [InlineKeyboardButton("🎡 دولاب الحظ", callback_data="wheel_menu")],
        [InlineKeyboardButton(t("btn_stats", lang), callback_data="my_stats")],
        [InlineKeyboardButton("📞 الدعم والمساعدة", callback_data="support_menu")],
        [InlineKeyboardButton(t("btn_language", lang), callback_data="change_language")],
    ]
    if telegram_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(t("btn_admin", lang), callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    await query.edit_message_text(
        t("main_menu_title", lang, balance=db_user["balance"]),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user.id, lang),
    )


async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="set_lang_ar"),
            InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en"),
        ]
    ])
    await query.edit_message_text(
        "🌐 اختر لغتك:\n\nChoose your language:",
        reply_markup=keyboard,
    )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    lang = "ar" if query.data == "set_lang_ar" else "en"
    set_user_lang(user.id, lang)

    db_user = get_user_by_telegram_id(user.id)
    await query.edit_message_text(
        t("language_set", lang),
        parse_mode="Markdown",
    )
    await context.bot.send_message(
        chat_id=user.id,
        text=t("welcome", lang, name=format_user_name(dict(db_user)), balance=db_user["balance"]),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user.id, lang),
    )


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)

    with db() as conn:
        db_user = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (user.id,)
        ).fetchone()
        if not db_user:
            await query.edit_message_text(t("user_not_found", lang))
            return

        bets = conn.execute(
            "SELECT * FROM bets WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (db_user["id"],),
        ).fetchall()
        deposits = conn.execute(
            "SELECT * FROM deposits WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (db_user["id"],),
        ).fetchall()
        withdrawals = conn.execute(
            "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (db_user["id"],),
        ).fetchall()
        tickets = conn.execute(
            "SELECT COUNT(*) as cnt FROM lottery_tickets WHERE user_id = ?",
            (db_user["id"],),
        ).fetchone()

    text = t("stats_title", lang)
    text += t("stats_balance", lang, balance=db_user["balance"])
    text += t("stats_tickets", lang, count=tickets["cnt"])

    if bets:
        text += t("stats_bets", lang)
        for b in bets:
            status_emoji = {"pending": "⏳", "won": "✅", "lost": "❌"}.get(b["status"], "❓")
            text += f"  {status_emoji} {b['bet_type']} - {b['prediction']} (${b['entry_fee']})\n"
        text += "\n"

    if deposits:
        text += t("stats_deposits", lang)
        for d in deposits:
            status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(d["status"], "❓")
            text += f"  {status_emoji} ${d['amount']} - {d['network']}\n"
        text += "\n"

    if withdrawals:
        text += t("stats_withdrawals", lang)
        for w in withdrawals:
            status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(w["status"], "❓")
            text += f"  {status_emoji} ${w['amount']}\n"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )
