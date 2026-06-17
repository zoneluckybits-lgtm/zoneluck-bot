import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, get_referral_tree, format_user_name, set_setting, get_setting

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))

ADMIN_SET_TRC20, ADMIN_SET_BEP20 = range(300, 302)
ADMIN_ADD_MATCH_HOME, ADMIN_ADD_MATCH_AWAY, ADMIN_ADD_MATCH_TIME = range(310, 313)
ADMIN_RESULT_MATCH_ID, ADMIN_RESULT_SCORE, ADMIN_RESULT_YELLOW, ADMIN_RESULT_RED, ADMIN_RESULT_PENALTY = range(320, 325)
ADMIN_DEPOSIT_AMOUNT = range(330, 331)
ADMIN_LOTTERY_FIRST, ADMIN_LOTTERY_SECOND, ADMIN_LOTTERY_THIRD = range(340, 343)


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user or (update.callback_query.from_user if update.callback_query else None)
        if not user or user.id != ADMIN_ID:
            if update.callback_query:
                await update.callback_query.answer("❌ غير مصرح لك.", show_alert=True)
            else:
                await update.message.reply_text("❌ غير مصرح لك.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with db() as conn:
        user_count = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
        pending_deposits = conn.execute(
            "SELECT COUNT(*) as cnt FROM deposits WHERE status = 'pending'"
        ).fetchone()["cnt"]
        pending_withdrawals = conn.execute(
            "SELECT COUNT(*) as cnt FROM withdrawals WHERE status = 'pending'"
        ).fetchone()["cnt"]
        active_tickets = conn.execute(
            "SELECT COUNT(*) as cnt FROM lottery_tickets WHERE status = 'active' AND prize_amount = 0"
        ).fetchone()["cnt"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"👥 المستخدمون ({user_count})", callback_data="admin_users")],
        [
            InlineKeyboardButton(f"📥 إيداعات ({pending_deposits})", callback_data="admin_deposits"),
            InlineKeyboardButton(f"📤 سحوبات ({pending_withdrawals})", callback_data="admin_withdrawals"),
        ],
        [InlineKeyboardButton("⚽ إدارة المباريات", callback_data="admin_matches")],
        [InlineKeyboardButton("🎟 اليانصيب", callback_data="admin_lottery")],
        [InlineKeyboardButton("⚙️ إعدادات المحافظ", callback_data="admin_wallets")],
        [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
    ])

    await query.edit_message_text(
        f"🔧 *لوحة تحكم الأدمن*\n\n"
        f"👥 المستخدمون: {user_count}\n"
        f"📥 إيداعات معلقة: {pending_deposits}\n"
        f"📤 سحوبات معلقة: {pending_withdrawals}\n"
        f"🎟 تذاكر يانصيب نشطة: {active_tickets}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@admin_only
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with db() as conn:
        users = conn.execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT 20"
        ).fetchall()

    if not users:
        await query.edit_message_text(
            "ℹ️ لا يوجد مستخدمون.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
            ),
        )
        return

    buttons = []
    for u in users:
        name = format_user_name(dict(u))
        buttons.append([
            InlineKeyboardButton(
                f"{name} — ${u['balance']:.2f}",
                callback_data=f"admin_user_{u['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.edit_message_text(
        "👥 *قائمة المستخدمين* (آخر 20):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@admin_only
async def admin_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[-1])

    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            await query.edit_message_text("❌ المستخدم غير موجود.")
            return

        bets = conn.execute(
            "SELECT b.*, m.team_home, m.team_away FROM bets b JOIN matches m ON b.match_id = m.id WHERE b.user_id = ? ORDER BY b.created_at DESC LIMIT 5",
            (user_id,),
        ).fetchall()
        deposits = conn.execute(
            "SELECT * FROM deposits WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (user_id,),
        ).fetchall()
        withdrawals = conn.execute(
            "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (user_id,),
        ).fetchall()
        tickets = conn.execute(
            "SELECT * FROM lottery_tickets WHERE user_id = ? ORDER BY purchased_at DESC LIMIT 5",
            (user_id,),
        ).fetchall()

    referrer, downline = get_referral_tree(user_id)

    text = f"👤 *{format_user_name(dict(user))}*\n"
    text += f"🆔 TG ID: `{user['telegram_id']}`\n"
    text += f"💰 الرصيد: ${user['balance']:.2f}\n"
    text += f"📅 التسجيل: {user['joined_at'][:10] if user['joined_at'] else 'N/A'}\n\n"

    if referrer:
        text += f"👆 دُعي بواسطة: {format_user_name(dict(referrer))}\n"
    text += f"👇 المدعوون: {len(downline)}\n\n"

    if bets:
        text += "⚽ *الرهانات الأخيرة:*\n"
        for b in bets:
            s = {"pending": "⏳", "won": "✅", "lost": "❌"}.get(b["status"], "❓")
            text += f"  {s} {b['team_home']} vs {b['team_away']} | {b['bet_type']} | {b['prediction']}\n"
        text += "\n"

    if deposits:
        text += "📥 *الإيداعات الأخيرة:*\n"
        for d in deposits:
            s = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(d["status"], "❓")
            text += f"  {s} ${d['amount']} ({d['network']})\n"
        text += "\n"

    if withdrawals:
        text += "📤 *السحوبات الأخيرة:*\n"
        for w in withdrawals:
            s = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(w["status"], "❓")
            text += f"  {s} ${w['amount']}\n"
        text += "\n"

    if downline:
        text += "🌳 *شجرة الإحالة (المدعوون):*\n"
        for u in downline[:5]:
            text += f"  • {format_user_name(dict(u))}\n"
        if len(downline) > 5:
            text += f"  ... و{len(downline) - 5} آخرين\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للمستخدمين", callback_data="admin_users")]
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@admin_only
async def admin_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with db() as conn:
        deposits = conn.execute(
            """SELECT d.*, u.full_name, u.username, u.telegram_id
               FROM deposits d JOIN users u ON d.user_id = u.id
               WHERE d.status = 'pending' ORDER BY d.created_at DESC LIMIT 10""",
        ).fetchall()

    if not deposits:
        await query.edit_message_text(
            "✅ لا توجد إيداعات معلقة.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
            ),
        )
        return

    text = "📥 *الإيداعات المعلقة:*\n\n"
    buttons = []
    for d in deposits:
        name = d["username"] or d["full_name"] or str(d["telegram_id"])
        text += f"#{d['id']} | @{name} | {d['network']} | الهاش: {d['tx_hash'] or 'صورة'}\n"
        buttons.append([
            InlineKeyboardButton(
                f"#{d['id']} — @{name} ({d['network']})",
                callback_data=f"admin_dep_detail_{d['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@admin_only
async def admin_deposit_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deposit_id = int(query.data.split("_")[-1])

    with db() as conn:
        d = conn.execute(
            """SELECT d.*, u.full_name, u.username, u.telegram_id
               FROM deposits d JOIN users u ON d.user_id = u.id WHERE d.id = ?""",
            (deposit_id,),
        ).fetchone()

    if not d:
        await query.edit_message_text("❌ الإيداع غير موجود.")
        return

    name = d["username"] or d["full_name"] or str(d["telegram_id"])
    text = f"📥 *إيداع #{deposit_id}*\n\n"
    text += f"👤 المستخدم: @{name}\n"
    text += f"🌐 الشبكة: {d['network']}\n"
    text += f"🔗 الهاش: `{d['tx_hash'] or 'لا يوجد'}`\n"
    text += f"📅 التاريخ: {d['created_at'][:16]}\n\n"
    text += "أدخل المبلغ المُودَع لقبوله، أو اضغط رفض:"

    context.user_data["admin_deposit_id"] = deposit_id
    context.user_data["admin_deposit_user_id"] = d["user_id"]
    context.user_data["admin_deposit_telegram_id"] = d["telegram_id"]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ قبول", callback_data=f"admin_approve_deposit_{deposit_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_deposit_{deposit_id}"),
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_deposits")],
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@admin_only
async def admin_approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deposit_id = int(query.data.split("_")[-1])

    with db() as conn:
        d = conn.execute(
            """SELECT d.*, u.telegram_id, u.referred_by, u.referral_rewarded
               FROM deposits d JOIN users u ON d.user_id = u.id WHERE d.id = ?""",
            (deposit_id,),
        ).fetchone()

        if not d or d["status"] != "pending":
            await query.answer("❌ الإيداع غير موجود أو تمت معالجته.", show_alert=True)
            return

        amount = d["amount"] if d["amount"] else 0

        if amount <= 0:
            await query.edit_message_text(
                "⚠️ أدخل مبلغ الإيداع أولاً:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_dep_detail_{deposit_id}")]
                ]),
            )
            context.user_data["awaiting_deposit_amount_for"] = deposit_id
            return

        conn.execute(
            "UPDATE deposits SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (deposit_id,),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (amount, d["user_id"]),
        )

        referral_reward_given = False
        if d["referred_by"] and not d["referral_rewarded"]:
            first_approved = conn.execute(
                """SELECT COUNT(*) as cnt FROM deposits
                   WHERE user_id = ? AND status = 'approved' AND id != ?""",
                (d["user_id"], deposit_id),
            ).fetchone()["cnt"]

            if first_approved == 0:
                conn.execute(
                    "UPDATE users SET balance = balance + 0.50 WHERE id = ?",
                    (d["referred_by"],),
                )
                conn.execute(
                    "UPDATE users SET referral_rewarded = 1 WHERE id = ?",
                    (d["user_id"],),
                )
                referral_reward_given = True
                referrer = conn.execute(
                    "SELECT telegram_id FROM users WHERE id = ?", (d["referred_by"],)
                ).fetchone()

    await query.edit_message_text(
        f"✅ تم قبول الإيداع #{deposit_id}\nالمبلغ: ${amount:.2f}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للإيداعات", callback_data="admin_deposits")]]
        ),
    )

    try:
        await context.bot.send_message(
            chat_id=d["telegram_id"],
            text=f"✅ *تم قبول إيداعك!*\n\nالمبلغ المُضاف: ${amount:.2f}\nشكراً لك!",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    if referral_reward_given and referrer:
        try:
            await context.bot.send_message(
                chat_id=referrer["telegram_id"],
                text="🎉 *مكافأة الإحالة!*\n\nصديقك الذي دعوته أكمل أول إيداع ناجح!\nتم إضافة $0.50 إلى رصيدك. 🎁",
                parse_mode="Markdown",
            )
        except Exception:
            pass


@admin_only
async def admin_reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deposit_id = int(query.data.split("_")[-1])

    with db() as conn:
        d = conn.execute(
            "SELECT * FROM deposits WHERE id = ?", (deposit_id,)
        ).fetchone()

        if not d or d["status"] != "pending":
            await query.answer("❌ الإيداع غير موجود أو تمت معالجته.", show_alert=True)
            return

        conn.execute(
            "UPDATE deposits SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (deposit_id,),
        )
        user = conn.execute("SELECT telegram_id FROM users WHERE id = ?", (d["user_id"],)).fetchone()

    await query.edit_message_text(
        f"❌ تم رفض الإيداع #{deposit_id}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للإيداعات", callback_data="admin_deposits")]]
        ),
    )

    try:
        await context.bot.send_message(
            chat_id=user["telegram_id"],
            text=f"❌ *تم رفض طلب إيداعك #{deposit_id}*\n\nتواصل مع الدعم إذا كان لديك استفسار.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


@admin_only
async def admin_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with db() as conn:
        withdrawals = conn.execute(
            """SELECT w.*, u.full_name, u.username, u.telegram_id
               FROM withdrawals w JOIN users u ON w.user_id = u.id
               WHERE w.status = 'pending' ORDER BY w.created_at DESC LIMIT 10""",
        ).fetchall()

    if not withdrawals:
        await query.edit_message_text(
            "✅ لا توجد سحوبات معلقة.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
            ),
        )
        return

    buttons = []
    for w in withdrawals:
        name = w["username"] or w["full_name"] or str(w["telegram_id"])
        buttons.append([
            InlineKeyboardButton(
                f"#{w['id']} — @{name} — ${w['amount']}",
                callback_data=f"admin_wd_detail_{w['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.edit_message_text(
        "📤 *السحوبات المعلقة:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@admin_only
async def admin_withdrawal_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wd_id = int(query.data.split("_")[-1])

    with db() as conn:
        w = conn.execute(
            """SELECT w.*, u.full_name, u.username, u.telegram_id
               FROM withdrawals w JOIN users u ON w.user_id = u.id WHERE w.id = ?""",
            (wd_id,),
        ).fetchone()

    if not w:
        await query.edit_message_text("❌ السحب غير موجود.")
        return

    name = w["username"] or w["full_name"] or str(w["telegram_id"])
    text = f"📤 *سحب #{wd_id}*\n\n"
    text += f"👤 المستخدم: @{name}\n"
    text += f"💵 المبلغ: ${w['amount']:.2f}\n"
    text += f"📍 العنوان: `{w['wallet_address']}`\n"
    text += f"📅 التاريخ: {w['created_at'][:16]}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ قبول", callback_data=f"admin_approve_wd_{wd_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_wd_{wd_id}"),
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_withdrawals")],
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@admin_only
async def admin_approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wd_id = int(query.data.split("_")[-1])

    with db() as conn:
        w = conn.execute(
            "SELECT w.*, u.telegram_id FROM withdrawals w JOIN users u ON w.user_id = u.id WHERE w.id = ?",
            (wd_id,),
        ).fetchone()

        if not w or w["status"] != "pending":
            await query.answer("❌ السحب غير موجود أو تمت معالجته.", show_alert=True)
            return

        conn.execute(
            "UPDATE withdrawals SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (wd_id,),
        )

    await query.edit_message_text(
        f"✅ تم قبول السحب #{wd_id} (${w['amount']:.2f})",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للسحوبات", callback_data="admin_withdrawals")]]
        ),
    )
    try:
        await context.bot.send_message(
            chat_id=w["telegram_id"],
            text=f"✅ *تم قبول طلب سحبك!*\n\nالمبلغ: ${w['amount']:.2f}\nسيصلك قريباً. 💸",
            parse_mode="Markdown",
        )
    except Exception:
        pass


@admin_only
async def admin_reject_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    wd_id = int(query.data.split("_")[-1])

    with db() as conn:
        w = conn.execute(
            "SELECT w.*, u.telegram_id FROM withdrawals w JOIN users u ON w.user_id = u.id WHERE w.id = ?",
            (wd_id,),
        ).fetchone()

        if not w or w["status"] != "pending":
            await query.answer("❌ السحب غير موجود أو تمت معالجته.", show_alert=True)
            return

        conn.execute(
            "UPDATE withdrawals SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (wd_id,),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (w["amount"], w["user_id"]),
        )

    await query.edit_message_text(
        f"❌ تم رفض السحب #{wd_id} وإعادة المبلغ للمستخدم.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للسحوبات", callback_data="admin_withdrawals")]]
        ),
    )
    try:
        await context.bot.send_message(
            chat_id=w["telegram_id"],
            text=f"❌ *تم رفض طلب سحبك #{wd_id}*\n\nتم إعادة المبلغ ${w['amount']:.2f} إلى رصيدك.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


@admin_only
async def admin_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with db() as conn:
        matches = conn.execute(
            "SELECT * FROM matches ORDER BY match_time DESC LIMIT 15"
        ).fetchall()

    keyboard = [[InlineKeyboardButton("➕ إضافة مباراة", callback_data="admin_add_match")]]
    for m in matches:
        status_icon = {"upcoming": "⏳", "finished": "✅", "cancelled": "❌"}.get(m["status"], "❓")
        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} {m['team_home']} vs {m['team_away']} | {m['match_time'][:10]}",
                callback_data=f"admin_match_detail_{m['id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])

    await query.edit_message_text(
        "⚽ *إدارة المباريات:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@admin_only
async def admin_add_match_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚽ أدخل اسم الفريق الأول (المضيف):")
    return ADMIN_ADD_MATCH_HOME


async def admin_add_match_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    context.user_data["match_home"] = update.message.text.strip()
    await update.message.reply_text("⚽ أدخل اسم الفريق الثاني (الضيف):")
    return ADMIN_ADD_MATCH_AWAY


async def admin_add_match_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    context.user_data["match_away"] = update.message.text.strip()
    await update.message.reply_text(
        "🕐 أدخل موعد المباراة بالصيغة التالية:\nYYYY-MM-DD HH:MM\nمثال: 2025-07-15 20:00"
    )
    return ADMIN_ADD_MATCH_TIME


async def admin_add_match_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    time_str = update.message.text.strip()
    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌ صيغة التاريخ غير صحيحة. حاول مجدداً:\nYYYY-MM-DD HH:MM")
        return ADMIN_ADD_MATCH_TIME

    home = context.user_data.get("match_home")
    away = context.user_data.get("match_away")

    with db() as conn:
        conn.execute(
            "INSERT INTO matches (team_home, team_away, match_time) VALUES (?, ?, ?)",
            (home, away, time_str),
        )

    await update.message.reply_text(
        f"✅ تم إضافة المباراة:\n⚽ {home} vs {away}\n🕐 {time_str}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للمباريات", callback_data="admin_matches")]]
        ),
    )
    context.user_data.clear()
    return ConversationHandler.END


@admin_only
async def admin_match_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match_id = int(query.data.split("_")[-1])

    with db() as conn:
        m = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        bets_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM bets WHERE match_id = ?", (match_id,)
        ).fetchone()["cnt"]

    if not m:
        await query.edit_message_text("❌ المباراة غير موجودة.")
        return

    text = f"⚽ *{m['team_home']} vs {m['team_away']}*\n"
    text += f"📅 الموعد: {m['match_time'][:16]}\n"
    text += f"📊 الحالة: {m['status']}\n"
    text += f"🎯 عدد الرهانات: {bets_count}\n"

    if m["status"] == "finished":
        text += f"\n✅ النتيجة النهائية: {m['result_home']}-{m['result_away']}\n"
        if m["yellow_card_players"]:
            text += f"🟡 بطاقات صفراء: {m['yellow_card_players']}\n"
        if m["red_card_players"]:
            text += f"🔴 بطاقات حمراء: {m['red_card_players']}\n"
        if m["penalty_score_home"] is not None:
            text += f"⚡ ركلات الترجيح: {m['penalty_score_home']}-{m['penalty_score_away']}\n"

    keyboard = []
    if m["status"] == "upcoming":
        keyboard.append([
            InlineKeyboardButton("📋 إدخال النتيجة", callback_data=f"admin_enter_result_{match_id}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_matches")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_enter_result_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match_id = int(query.data.split("_")[-1])
    context.user_data["result_match_id"] = match_id

    with db() as conn:
        m = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()

    await query.edit_message_text(
        f"📋 إدخال نتيجة: {m['team_home']} vs {m['team_away']}\n\n"
        f"أدخل النتيجة النهائية (مثال: 2-1):"
    )
    return ADMIN_RESULT_SCORE


async def admin_result_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    score = update.message.text.strip()
    try:
        parts = score.split("-")
        assert len(parts) == 2
        int(parts[0]), int(parts[1])
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ صيغة غير صحيحة. مثال: 2-1")
        return ADMIN_RESULT_SCORE

    context.user_data["result_score"] = score
    await update.message.reply_text(
        "🟡 أدخل أسماء لاعبي البطاقات الصفراء (مفصولة بفاصلة)، أو أرسل `-` إذا لا يوجد:"
    )
    return ADMIN_RESULT_YELLOW


async def admin_result_yellow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    yellow = update.message.text.strip()
    context.user_data["result_yellow"] = "" if yellow == "-" else yellow
    await update.message.reply_text(
        "🔴 أدخل أسماء لاعبي البطاقات الحمراء (مفصولة بفاصلة)، أو أرسل `-` إذا لا يوجد:"
    )
    return ADMIN_RESULT_RED


async def admin_result_red(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    red = update.message.text.strip()
    context.user_data["result_red"] = "" if red == "-" else red
    await update.message.reply_text(
        "⚡ أدخل نتيجة ركلات الترجيح (مثال: 4-3)، أو أرسل `-` إذا لم تصل المباراة لركلات:"
    )
    return ADMIN_RESULT_PENALTY


async def admin_result_penalty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    penalty = update.message.text.strip()
    penalty_home = None
    penalty_away = None

    if penalty != "-":
        try:
            parts = penalty.split("-")
            assert len(parts) == 2
            penalty_home = int(parts[0])
            penalty_away = int(parts[1])
        except (ValueError, AssertionError):
            await update.message.reply_text("❌ صيغة غير صحيحة. مثال: 4-3 أو `-`")
            return ADMIN_RESULT_PENALTY

    match_id = context.user_data["result_match_id"]
    score = context.user_data["result_score"]
    yellow = context.user_data["result_yellow"]
    red = context.user_data["result_red"]
    score_parts = score.split("-")
    result_home = int(score_parts[0])
    result_away = int(score_parts[1])

    with db() as conn:
        conn.execute(
            """UPDATE matches SET status='finished', result_home=?, result_away=?,
               yellow_card_players=?, red_card_players=?, penalty_score_home=?, penalty_score_away=?
               WHERE id=?""",
            (result_home, result_away, yellow, red, penalty_home, penalty_away, match_id),
        )

        bets = conn.execute(
            "SELECT b.*, u.telegram_id FROM bets b JOIN users u ON b.user_id = u.id WHERE b.match_id = ? AND b.status = 'pending'",
            (match_id,),
        ).fetchall()

        winners = []
        for bet in bets:
            won = False
            pred = bet["prediction"].strip().lower()

            if bet["bet_type"] == "correct_score":
                won = pred == score.lower()
            elif bet["bet_type"] == "yellow_card":
                yellow_list = [p.strip().lower() for p in yellow.split(",") if p.strip()]
                won = pred in yellow_list
            elif bet["bet_type"] == "red_card":
                red_list = [p.strip().lower() for p in red.split(",") if p.strip()]
                won = pred in red_list
            elif bet["bet_type"] == "penalty_score":
                if penalty_home is not None:
                    won = pred == f"{penalty_home}-{penalty_away}"

            status = "won" if won else "lost"
            conn.execute(
                "UPDATE bets SET status=?, settled_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, bet["id"]),
            )
            if won:
                conn.execute(
                    "UPDATE users SET balance = balance + ? WHERE id=?",
                    (bet["payout"], bet["user_id"]),
                )
                winners.append((bet["telegram_id"], bet["payout"], bet["bet_type"], bet["prediction"]))

    for tg_id, payout, bet_type, prediction in winners:
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=f"🎉 *مبروك! فزت في رهانك!*\n\n"
                     f"⚽ نوع الرهان: {bet_type}\n"
                     f"🎯 توقعك: {prediction}\n"
                     f"💰 تم إضافة ${payout:.2f} إلى رصيدك!",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ تم تسجيل النتيجة وتسوية الرهانات!\n"
        f"النتيجة: {score}\n"
        f"الفائزون: {len(winners)}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للمباريات", callback_data="admin_matches")]]
        ),
    )
    context.user_data.clear()
    return ConversationHandler.END


@admin_only
async def admin_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    trc20 = get_setting("trc20_address")
    bep20 = get_setting("bep20_address")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل TRC-20", callback_data="admin_set_trc20")],
        [InlineKeyboardButton("✏️ تعديل BEP-20", callback_data="admin_set_bep20")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")],
    ])
    await query.edit_message_text(
        f"⚙️ *عناوين محافظ الإيداع:*\n\n"
        f"🔵 TRC-20: `{trc20 or 'غير مضبوط'}`\n"
        f"🟡 BEP-20: `{bep20 or 'غير مضبوط'}`",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@admin_only
async def admin_set_trc20_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔵 أدخل عنوان محفظة TRC-20 الجديد:")
    return ADMIN_SET_TRC20


async def admin_set_trc20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    set_setting("trc20_address", update.message.text.strip())
    await update.message.reply_text(
        "✅ تم تحديث عنوان TRC-20.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للإعدادات", callback_data="admin_wallets")]]
        ),
    )
    return ConversationHandler.END


@admin_only
async def admin_set_bep20_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🟡 أدخل عنوان محفظة BEP-20 الجديد:")
    return ADMIN_SET_BEP20


async def admin_set_bep20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    set_setting("bep20_address", update.message.text.strip())
    await update.message.reply_text(
        "✅ تم تحديث عنوان BEP-20.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للإعدادات", callback_data="admin_wallets")]]
        ),
    )
    return ConversationHandler.END


@admin_only
async def admin_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with db() as conn:
        tickets = conn.execute(
            "SELECT lt.*, u.username, u.full_name FROM lottery_tickets lt JOIN users u ON lt.user_id = u.id WHERE lt.status = 'active' AND lt.prize_amount = 0 ORDER BY lt.purchased_at DESC"
        ).fetchall()

    text = f"🎟 *لوحة اليانصيب*\n\n"
    text += f"عدد التذاكر النشطة: {len(tickets)}\n\n"

    if tickets:
        text += "*التذاكر:*\n"
        for t in tickets[:20]:
            name = t["username"] or t["full_name"] or "مجهول"
            text += f"  `{t['ticket_number']}` — @{name}\n"
        if len(tickets) > 20:
            text += f"  ... و{len(tickets) - 20} أخرى\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 إعلان الفائزين", callback_data="admin_draw_lottery")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")],
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@admin_only
async def admin_draw_lottery_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🥇 أدخل رقم تذكرة الجائزة الأولى ($100):"
    )
    return ADMIN_LOTTERY_FIRST


async def admin_lottery_first(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    context.user_data["lottery_first"] = update.message.text.strip().upper()
    await update.message.reply_text("🥈 أدخل رقم تذكرة الجائزة الثانية ($200):")
    return ADMIN_LOTTERY_SECOND


async def admin_lottery_second(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    context.user_data["lottery_second"] = update.message.text.strip().upper()
    await update.message.reply_text("🥉 أدخل رقم تذكرة الجائزة الثالثة ($500):")
    return ADMIN_LOTTERY_THIRD


async def admin_lottery_third(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    third = update.message.text.strip().upper()
    first = context.user_data["lottery_first"]
    second = context.user_data["lottery_second"]

    prizes = {first: (1, 100.0), second: (2, 200.0), third: (3, 500.0)}

    results = []
    with db() as conn:
        draw_cursor = conn.execute(
            "INSERT INTO lottery_draws (first_ticket, second_ticket, third_ticket) VALUES (?, ?, ?)",
            (first, second, third),
        )
        draw_id = draw_cursor.lastrowid

        for ticket_num, (tier, prize) in prizes.items():
            ticket = conn.execute(
                "SELECT lt.*, u.telegram_id FROM lottery_tickets lt JOIN users u ON lt.user_id = u.id WHERE lt.ticket_number = ?",
                (ticket_num,),
            ).fetchone()

            if ticket:
                conn.execute(
                    "UPDATE lottery_tickets SET prize_tier=?, prize_amount=?, draw_id=?, status='won' WHERE id=?",
                    (tier, prize, draw_id, ticket["id"]),
                )
                conn.execute(
                    "UPDATE users SET balance = balance + ? WHERE id=?",
                    (prize, ticket["user_id"]),
                )
                results.append((ticket["telegram_id"], prize, tier, ticket_num))

    tier_names = {1: "🥇 الأولى", 2: "🥈 الثانية", 3: "🥉 الثالثة"}
    for tg_id, prize, tier, ticket_num in results:
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=f"🎉 *مبروك! فزت في اليانصيب!*\n\n"
                     f"🎟 رقم تذكرتك: `{ticket_num}`\n"
                     f"🏆 الجائزة {tier_names[tier]}: ${prize:.2f}\n\n"
                     f"تم إضافة المبلغ إلى رصيدك! 💰",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ *تم إعلان نتائج اليانصيب!*\n\n"
        f"🥇 الأولى: `{first}`\n"
        f"🥈 الثانية: `{second}`\n"
        f"🥉 الثالثة: `{third}`\n\n"
        f"الفائزون الذين وجدنا تذاكرهم: {len(results)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 لليانصيب", callback_data="admin_lottery")]]
        ),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("❌ تم الإلغاء.")
    return ConversationHandler.END
