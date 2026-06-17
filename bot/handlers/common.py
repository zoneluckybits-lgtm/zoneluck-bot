import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from utils import register_user, get_user_by_telegram_id, format_user_name

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))


def is_admin(telegram_id):
    return telegram_id == ADMIN_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    referred_by = None
    if args and args[0].startswith("ref_"):
        try:
            referred_by = int(args[0][4:])
        except ValueError:
            pass

    register_user(user.id, user.username, user.full_name, referred_by)

    db_user = get_user_by_telegram_id(user.id)
    await update.message.reply_text(
        f"🎯 *مرحباً بك في Zone Luck!*\n\n"
        f"👤 اسمك: {format_user_name(dict(db_user))}\n"
        f"💰 رصيدك: ${db_user['balance']:.2f}\n\n"
        f"اختر من القائمة أدناه:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user.id),
    )


def main_menu_keyboard(telegram_id):
    buttons = [
        [
            InlineKeyboardButton("💰 محفظتي", callback_data="wallet"),
            InlineKeyboardButton("⚽ الرهانات", callback_data="matches_menu"),
        ],
        [
            InlineKeyboardButton("🎟 اليانصيب", callback_data="lottery_menu"),
            InlineKeyboardButton("👥 الإحالة", callback_data="referral"),
        ],
        [InlineKeyboardButton("📊 رصيدي وسجلاتي", callback_data="my_stats")],
    ]
    if telegram_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("🔧 لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    await query.edit_message_text(
        f"🎯 *القائمة الرئيسية*\n\n"
        f"💰 رصيدك: ${db_user['balance']:.2f}",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user.id),
    )


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    with db() as conn:
        db_user = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (user.id,)
        ).fetchone()
        if not db_user:
            await query.edit_message_text("❌ لم يتم العثور على حسابك.")
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

    text = f"📊 *إحصائياتك*\n\n"
    text += f"💰 الرصيد: ${db_user['balance']:.2f}\n"
    text += f"🎟 تذاكر اليانصيب: {tickets['cnt']}\n\n"

    if bets:
        text += "⚽ *آخر الرهانات:*\n"
        for b in bets:
            status_emoji = {"pending": "⏳", "won": "✅", "lost": "❌"}.get(b["status"], "❓")
            text += f"  {status_emoji} {b['bet_type']} - {b['prediction']} (${b['entry_fee']})\n"
        text += "\n"

    if deposits:
        text += "📥 *آخر الإيداعات:*\n"
        for d in deposits:
            status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(d["status"], "❓")
            text += f"  {status_emoji} ${d['amount']} - {d['network']}\n"
        text += "\n"

    if withdrawals:
        text += "📤 *آخر السحوبات:*\n"
        for w in withdrawals:
            status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(w["status"], "❓")
            text += f"  {status_emoji} ${w['amount']}\n"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )
