from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, get_user_lang
from lang import t

BET_PREDICTION = 100

BET_TYPES = {
    "correct_score": {"fee": 2.0, "payout": 10.0},
    "yellow_card":   {"fee": 3.0, "payout": 25.0},
    "red_card":      {"fee": 4.0, "payout": 50.0},
    "penalty_score": {"fee": 5.0, "payout": 100.0},
}


def get_bet_info(key, lang):
    names = {
        "correct_score": (t("bet_correct_score_name", lang), t("bet_correct_score_prompt", lang)),
        "yellow_card":   (t("bet_yellow_card_name", lang),   t("bet_yellow_card_prompt", lang)),
        "red_card":      (t("bet_red_card_name", lang),      t("bet_red_card_prompt", lang)),
        "penalty_score": (t("bet_penalty_name", lang),       t("bet_penalty_prompt", lang)),
    }
    return names.get(key, (key, ""))


def get_matches_by_category(category):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S")
    week_end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    with db() as conn:
        if category == "today":
            return conn.execute(
                "SELECT * FROM matches WHERE match_time >= ? AND match_time <= ? AND status = 'upcoming' ORDER BY match_time",
                (now, today_end),
            ).fetchall()
        elif category == "week":
            return conn.execute(
                "SELECT * FROM matches WHERE match_time >= ? AND match_time <= ? AND status = 'upcoming' ORDER BY match_time",
                (now, week_end),
            ).fetchall()
        else:
            return conn.execute(
                "SELECT * FROM matches WHERE status = 'upcoming' ORDER BY match_time LIMIT 20"
            ).fetchall()


async def matches_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_today", lang), callback_data="matches_today")],
        [InlineKeyboardButton(t("btn_week", lang), callback_data="matches_week")],
        [InlineKeyboardButton(t("btn_all", lang), callback_data="matches_all")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")],
    ])
    await query.edit_message_text(
        t("matches_title", lang),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def show_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    category = query.data.replace("matches_", "")

    matches = get_matches_by_category(category)
    category_names = {
        "today": t("category_today", lang),
        "week":  t("category_week", lang),
        "all":   t("category_all", lang),
    }

    if not matches:
        await query.edit_message_text(
            t("no_matches", lang),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="matches_menu")]]
            ),
        )
        return

    buttons = []
    for m in matches:
        match_time = m["match_time"][:16] if m["match_time"] else "?"
        buttons.append([
            InlineKeyboardButton(
                f"⚽ {m['team_home']} vs {m['team_away']} | {match_time}",
                callback_data=f"bet_match_{m['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton(t("btn_back_short", lang), callback_data="matches_menu")])

    await query.edit_message_text(
        t("matches_list_title", lang, category=category_names.get(category, category)),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_bet_types(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    match_id = int(query.data.split("_")[-1])

    with db() as conn:
        match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()

    if not match:
        await query.edit_message_text(t("match_not_found", lang))
        return

    context.user_data["bet_match_id"] = match_id
    context.user_data["bet_match_name"] = f"{match['team_home']} vs {match['team_away']}"

    buttons = []
    for key, info in BET_TYPES.items():
        name, _ = get_bet_info(key, lang)
        buttons.append([
            InlineKeyboardButton(
                f"{name} — ${info['fee']} ← ${info['payout']}",
                callback_data=f"bettype_{key}",
            )
        ])
    buttons.append([InlineKeyboardButton(t("btn_back_short", lang), callback_data="matches_all")])

    await query.edit_message_text(
        t("choose_bet_type", lang, home=match["team_home"], away=match["team_away"], time=match["match_time"][:16]),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def bet_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    bet_type = query.data.replace("bettype_", "")

    if bet_type not in BET_TYPES:
        await query.edit_message_text(t("invalid_bet_type", lang))
        return ConversationHandler.END

    info = BET_TYPES[bet_type]
    name, prompt = get_bet_info(bet_type, lang)
    context.user_data["bet_type"] = bet_type
    context.user_data["bet_fee"] = info["fee"]
    context.user_data["bet_payout"] = info["payout"]

    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < info["fee"]:
        await query.edit_message_text(
            t("insufficient_balance", lang, fee=info["fee"], balance=db_user["balance"]),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="matches_menu")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        t("bet_prompt", lang, name=name, fee=info["fee"], payout=info["payout"], prompt=prompt),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_cancel", lang), callback_data="cancel_bet")]]
        ),
    )
    return BET_PREDICTION


async def cancel_bet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(update.effective_user.id)
    context.user_data.clear()
    await query.edit_message_text(
        t("cancelled", lang),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="matches_menu")]]
        ),
    )
    return ConversationHandler.END


async def bet_prediction_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)
    prediction = update.message.text.strip()
    match_id = context.user_data.get("bet_match_id")
    bet_type = context.user_data.get("bet_type")
    fee = context.user_data.get("bet_fee")
    payout = context.user_data.get("bet_payout")
    match_name = context.user_data.get("bet_match_name", "")

    if not all([match_id, bet_type, fee, payout]):
        await update.message.reply_text(t("bet_error", lang))
        return ConversationHandler.END

    if db_user["balance"] < fee:
        await update.message.reply_text(
            t("insufficient_balance", lang, fee=fee, balance=db_user["balance"])
        )
        return ConversationHandler.END

    with db() as conn:
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE telegram_id = ?",
            (fee, user.id),
        )
        conn.execute(
            """INSERT INTO bets (user_id, match_id, bet_type, entry_fee, prediction, payout)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (db_user["id"], match_id, bet_type, fee, prediction, payout),
        )

    bet_name, _ = get_bet_info(bet_type, lang)
    await update.message.reply_text(
        t("bet_registered", lang, match=match_name, bet_name=bet_name,
          prediction=prediction, fee=fee, payout=payout),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text(t("cancelled", lang))
    return ConversationHandler.END
