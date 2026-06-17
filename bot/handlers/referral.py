from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import get_user_by_telegram_id, get_referral_tree, format_user_name


async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
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

    text = f"👥 *نظام الإحالة*\n\n"
    text += f"🔗 رابط الإحالة الخاص بك:\n`{referral_link}`\n\n"
    text += f"👤 عدد المدعوين: {referral_count}\n"
    text += f"✅ مكافآت مكتسبة: {rewarded_count} × $0.50 = ${rewarded_count * 0.5:.2f}\n\n"

    if referrer:
        text += f"👆 دعاك: {format_user_name(dict(referrer))}\n\n"

    if downline:
        text += "👇 *المدعوون منك:*\n"
        for u in downline[:10]:
            text += f"  • {format_user_name(dict(u))}\n"
        if len(downline) > 10:
            text += f"  ... و{len(downline) - 10} آخرين\n"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )
