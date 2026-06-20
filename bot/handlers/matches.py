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


def _fmt_time(val):
    """Return 'YYYY-MM-DD HH:MM' from a datetime object or string."""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M")
    if val:
        return str(val)[:16]
    return "?"


def get_matches_by_category(category):
    # naive datetime لتطابق تخزين PostgreSQL بدون timezone
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    week_end    = now + timedelta(days=7)

    with db() as conn:
        if category == "today":
            return conn.execute(
                "SELECT * FROM matches WHERE match_time >= ? AND match_time <= ? AND status = 'upcoming' ORDER BY match_time",
                (today_start, today_end),
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

    try:
        matches = get_matches_by_category(category)
    except Exception as e:
        await query.edit_message_text(
            f"❌ خطأ في تحميل المباريات: {e}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="matches_menu")]]
            ),
        )
        return

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
        match_time = _fmt_time(m["match_time"])
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

    try:
        with db() as conn:
            match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    except Exception as e:
        await query.edit_message_text(f"❌ خطأ: {e}")
        return

    if not match:
        await query.edit_message_text(t("match_not_found", lang))
        return

    context.user_data["bet_match_id"] = match_id
    context.user_data["bet_match_name"] = f"{match['team_home']} vs {match['team_away']}"
    context.user_data["bet_team_home"] = match["team_home"]
    context.user_data["bet_team_away"] = match["team_away"]

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
        t("choose_bet_type", lang, home=match["team_home"], away=match["team_away"],
          time=_fmt_time(match["match_time"])),
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
    name, _ = get_bet_info(bet_type, lang)
    context.user_data["bet_type"] = bet_type
    context.user_data["bet_fee"] = info["fee"]
    context.user_data["bet_payout"] = info["payout"]

    team_home = context.user_data.get("bet_team_home", "الفريق الأول")
    team_away = context.user_data.get("bet_team_away", "الفريق الثاني")

    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < info["fee"]:
        await query.edit_message_text(
            t("insufficient_balance", lang, fee=info["fee"], balance=db_user["balance"]),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="matches_menu")]]
            ),
        )
        return ConversationHandler.END

    # بناء prompt واضح مع أسماء الفرق
    if bet_type == "correct_score":
        prompt = (
            f"🏠 *{team_home}* (الرقم الأول)\n"
            f"✈️ *{team_away}* (الرقم الثاني)\n\n"
            f"أدخل توقعك للنتيجة:\n"
            f"`[أهداف {team_home}]-[أهداف {team_away}]`\n\n"
            f"مثال: `2-1` يعني {team_home} سجّل 2 و{team_away} سجّل 1"
        )
    elif bet_type == "penalty_score":
        prompt = (
            f"🏠 *{team_home}* (الرقم الأول)\n"
            f"✈️ *{team_away}* (الرقم الثاني)\n\n"
            f"أدخل نتيجة ركلات الترجيح:\n"
            f"`[{team_home}]-[{team_away}]`\n\n"
            f"مثال: `4-3` يعني {team_home} سجّل 4 و{team_away} سجّل 3"
        )
    elif bet_type == "yellow_card":
        prompt = f"أدخل اسم اللاعب الذي تتوقع أنه سيأخذ بطاقة صفراء:"
    else:  # red_card
        prompt = f"أدخل اسم اللاعب الذي تتوقع أنه سيأخذ بطاقة حمراء:"

    text = (
        f"⚽ *{team_home} vs {team_away}*\n\n"
        f"🎯 *{name}*\n"
        f"💵 رسوم الدخول: ${info['fee']}\n"
        f"🏆 الجائزة عند الفوز: ${info['payout']}\n\n"
        f"{prompt}"
    )

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
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

    # تحقق: هل المستخدم راهن على هذه المباراة مسبقاً؟
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM bets WHERE user_id = ? AND match_id = ?",
            (db_user["id"], match_id),
        ).fetchone()

    if existing:
        match_name = context.user_data.get("bet_match_name", "")
        await update.message.reply_text(
            f"⚠️ لقد راهنت مسبقاً على مباراة *{match_name}*\n\n"
            f"مسموح برهان واحد فقط لكل مباراة.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back", lang), callback_data="matches_menu")]]
            ),
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
