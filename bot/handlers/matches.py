from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id

BET_PREDICTION = 100

BET_TYPES = {
    "correct_score": {
        "name": "⚽ نتيجة صحيحة",
        "fee": 2.0,
        "payout": 10.0,
        "prompt": "أدخل توقعك للنتيجة النهائية (مثال: 2-1):",
    },
    "yellow_card": {
        "name": "🟡 بطاقة صفراء",
        "fee": 3.0,
        "payout": 25.0,
        "prompt": "أدخل اسم اللاعب الذي ستصله بطاقة صفراء:",
    },
    "red_card": {
        "name": "🔴 بطاقة حمراء",
        "fee": 4.0,
        "payout": 50.0,
        "prompt": "أدخل اسم اللاعب الذي ستصله بطاقة حمراء:",
    },
    "penalty_score": {
        "name": "⚡ ركلات الترجيح",
        "fee": 5.0,
        "payout": 100.0,
        "prompt": "أدخل نتيجة ركلات الترجيح (مثال: 4-3):",
    },
}


def get_matches_by_category(category):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S")
    week_end_ts = datetime.now(timezone.utc)
    from datetime import timedelta
    week_end = (week_end_ts + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

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

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 مباريات اليوم", callback_data="matches_today")],
        [InlineKeyboardButton("📆 مباريات الأسبوع", callback_data="matches_week")],
        [InlineKeyboardButton("🌍 كل المباريات", callback_data="matches_all")],
        [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
    ])
    await query.edit_message_text(
        "⚽ *قسم الرهانات*\n\nاختر فئة المباريات:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def show_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("matches_", "")

    matches = get_matches_by_category(category)
    category_names = {"today": "اليوم", "week": "الأسبوع", "all": "الكل"}

    if not matches:
        await query.edit_message_text(
            f"ℹ️ لا توجد مباريات متاحة لـ {category_names.get(category, category)} حالياً.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="matches_menu")]]
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
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="matches_menu")])

    await query.edit_message_text(
        f"⚽ *مباريات {category_names.get(category, category)}*\n\nاختر مباراة للمراهنة:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_bet_types(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match_id = int(query.data.split("_")[-1])

    with db() as conn:
        match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()

    if not match:
        await query.edit_message_text("❌ المباراة غير موجودة.")
        return

    context.user_data["bet_match_id"] = match_id
    context.user_data["bet_match_name"] = f"{match['team_home']} vs {match['team_away']}"

    buttons = []
    for key, info in BET_TYPES.items():
        buttons.append([
            InlineKeyboardButton(
                f"{info['name']} — ${info['fee']} ← ${info['payout']}",
                callback_data=f"bettype_{key}",
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="matches_all")])

    await query.edit_message_text(
        f"⚽ *{match['team_home']} vs {match['team_away']}*\n"
        f"🗓 {match['match_time'][:16]}\n\n"
        f"اختر نوع الرهان:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def bet_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bet_type = query.data.replace("bettype_", "")

    if bet_type not in BET_TYPES:
        await query.edit_message_text("❌ نوع رهان غير صحيح.")
        return ConversationHandler.END

    info = BET_TYPES[bet_type]
    context.user_data["bet_type"] = bet_type
    context.user_data["bet_fee"] = info["fee"]
    context.user_data["bet_payout"] = info["payout"]

    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < info["fee"]:
        await query.edit_message_text(
            f"❌ رصيدك غير كافٍ.\n"
            f"رسوم الرهان: ${info['fee']}\n"
            f"رصيدك: ${db_user['balance']:.2f}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="matches_menu")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"{info['name']}\n"
        f"💵 رسوم الدخول: ${info['fee']}\n"
        f"🏆 الجائزة عند الفوز: ${info['payout']}\n\n"
        f"{info['prompt']}",
    )
    return BET_PREDICTION


async def bet_prediction_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user_by_telegram_id(user.id)
    prediction = update.message.text.strip()
    match_id = context.user_data.get("bet_match_id")
    bet_type = context.user_data.get("bet_type")
    fee = context.user_data.get("bet_fee")
    payout = context.user_data.get("bet_payout")
    match_name = context.user_data.get("bet_match_name", "")

    if not all([match_id, bet_type, fee, payout]):
        await update.message.reply_text("❌ حدث خطأ. حاول مجدداً.")
        return ConversationHandler.END

    if db_user["balance"] < fee:
        await update.message.reply_text(
            f"❌ رصيدك غير كافٍ. رصيدك: ${db_user['balance']:.2f}"
        )
        return ConversationHandler.END

    with db() as conn:
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE telegram_id = ?",
            (fee, user.id),
        )
        cursor = conn.execute(
            """INSERT INTO bets (user_id, match_id, bet_type, entry_fee, prediction, payout)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (db_user["id"], match_id, bet_type, fee, prediction, payout),
        )

    info = BET_TYPES[bet_type]
    await update.message.reply_text(
        f"✅ *تم تسجيل رهانك!*\n\n"
        f"⚽ المباراة: {match_name}\n"
        f"{info['name']}\n"
        f"🎯 توقعك: {prediction}\n"
        f"💵 رسوم الدخول: ${fee}\n"
        f"🏆 الجائزة المحتملة: ${payout}\n\n"
        f"سيتم تسوية الرهان بعد انتهاء المباراة.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END
