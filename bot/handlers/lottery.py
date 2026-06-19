from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, generate_ticket_number, get_user_lang
from lang import t

LOTTERY_CONFIRM = 200
TICKET_PRICE = 5.0
PRIZES = {1: 100.0, 2: 200.0, 3: 500.0}


async def lottery_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
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

    text = t("lottery_title", lang, balance=db_user["balance"])

    if my_tickets:
        text += t("lottery_active_tickets", lang)
        for tk in my_tickets[:5]:
            text += f"  • `{tk['ticket_number']}`\n"
        if len(my_tickets) > 5:
            text += t("lottery_more_tickets", lang, count=len(my_tickets) - 5)

    if won_tickets:
        text += t("lottery_won_tickets", lang)
        for tk in won_tickets:
            text += f"  🎉 `{tk['ticket_number']}` — ${tk['prize_amount']:.2f}\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_buy_ticket", lang), callback_data="lottery_buy")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")],
    ])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def lottery_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < TICKET_PRICE:
        await query.edit_message_text(
            t("lottery_insufficient", lang, balance=db_user["balance"]),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="lottery_menu")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        t("lottery_confirm_msg", lang, after=db_user["balance"] - TICKET_PRICE),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(t("btn_confirm", lang), callback_data="lottery_confirm"),
                InlineKeyboardButton(t("btn_cancel", lang), callback_data="lottery_menu"),
            ]
        ]),
    )


async def lottery_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < TICKET_PRICE:
        await query.edit_message_text(t("lottery_insufficient_short", lang))
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
        t("lottery_bought", lang, ticket=ticket_number),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )
