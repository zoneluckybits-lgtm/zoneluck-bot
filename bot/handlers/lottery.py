from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, generate_ticket_number

LOTTERY_CONFIRM = 200

TICKET_PRICE = 5.0
PRIZES = {1: 100.0, 2: 200.0, 3: 500.0}


async def lottery_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    with db() as conn:
        my_tickets = conn.execute(
            "SELECT * FROM lottery_tickets WHERE user_id = ? AND status = 'active' ORDER BY purchased_at DESC LIMIT 10",
            (db_user["id"],),
        ).fetchall()

        won_tickets = conn.execute(
            "SELECT * FROM lottery_tickets WHERE user_id = ? AND prize_amount > 0 ORDER BY purchased_at DESC LIMIT 5",
            (db_user["id"],),
        ).fetchall()

    text = f"🎟 *يانصيب Zone Luck*\n\n"
    text += f"💵 سعر التذكرة: $5\n"
    text += f"🏆 الجوائز:\n"
    text += f"  🥇 الأولى: $100\n"
    text += f"  🥈 الثانية: $200\n"
    text += f"  🥉 الثالثة: $500\n\n"
    text += f"💰 رصيدك: ${db_user['balance']:.2f}\n\n"

    if my_tickets:
        text += f"🎫 *تذاكرك النشطة:*\n"
        for t in my_tickets[:5]:
            text += f"  • `{t['ticket_number']}`\n"
        if len(my_tickets) > 5:
            text += f"  ... و{len(my_tickets) - 5} أخرى\n"

    if won_tickets:
        text += f"\n🏆 *تذاكر فائزة:*\n"
        for t in won_tickets:
            text += f"  🎉 `{t['ticket_number']}` — ${t['prize_amount']:.2f}\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎟 شراء تذكرة ($5)", callback_data="lottery_buy")],
        [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
    ])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def lottery_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < TICKET_PRICE:
        await query.edit_message_text(
            f"❌ رصيدك غير كافٍ لشراء تذكرة.\n"
            f"رصيدك: ${db_user['balance']:.2f}\n"
            f"سعر التذكرة: $5",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="lottery_menu")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"🎟 *شراء تذكرة يانصيب*\n\n"
        f"السعر: $5\n"
        f"رصيدك بعد الشراء: ${db_user['balance'] - TICKET_PRICE:.2f}\n\n"
        f"هل تريد تأكيد الشراء؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تأكيد", callback_data="lottery_confirm"),
                InlineKeyboardButton("❌ إلغاء", callback_data="lottery_menu"),
            ]
        ]),
    )


async def lottery_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < TICKET_PRICE:
        await query.edit_message_text("❌ رصيدك غير كافٍ.")
        return

    ticket_number = generate_ticket_number()

    with db() as conn:
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE telegram_id = ?",
            (TICKET_PRICE, user.id),
        )
        conn.execute(
            "INSERT INTO lottery_tickets (user_id, ticket_number) VALUES (?, ?)",
            (db_user["id"], ticket_number),
        )

    await query.edit_message_text(
        f"✅ *تم شراء التذكرة بنجاح!*\n\n"
        f"🎟 رقم تذكرتك: `{ticket_number}`\n"
        f"احتفظ بهذا الرقم — سيُعلن عن النتائج قريباً!\n\n"
        f"بالتوفيق! 🍀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )
