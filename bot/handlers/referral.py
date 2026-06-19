from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import get_user_by_telegram_id, get_referral_tree, format_user_name, get_user_lang
from lang import t


async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    bot_info = await context.bot.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

    with db() as conn:
        referral_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE referred_by = ?",
            (db_user["id"],),
        ).fetchone()["cnt"]

        rewarded_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE referred_by = ? AND referral_rewarded = 1",
            (db_user["id"],),
        ).fetchone()["cnt"]

    referrer, downline = get_referral_tree(db_user["id"])

    text = t("referral_title", lang, link=referral_link, count=referral_count,
             rewarded=rewarded_count, earned=rewarded_count * 0.5)

    if referrer:
        text += t("referral_invited_by", lang, name=format_user_name(dict(referrer)))

    if downline:
        text += t("referral_downline", lang)
        for u in downline[:10]:
            text += f"  • {format_user_name(dict(u))}\n"
        if len(downline) > 10:
            text += t("referral_more", lang, count=len(downline) - 10)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )
