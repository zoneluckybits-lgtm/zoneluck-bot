import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, get_setting

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
DEPOSIT_AMOUNT_STATE = 500


async def admin_deposit_enter_amount_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    deposit_id = int(query.data.split("_")[-1])
    context.user_data["awaiting_deposit_amount_for"] = deposit_id
    await query.edit_message_text(
        f"💵 أدخل مبلغ الإيداع للطلب #{deposit_id} (بالدولار):"
    )
    return DEPOSIT_AMOUNT_STATE


async def admin_deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    deposit_id = context.user_data.get("awaiting_deposit_amount_for")
    if not deposit_id:
        return ConversationHandler.END

    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغاً صحيحاً أكبر من صفر.")
        return DEPOSIT_AMOUNT_STATE

    with db() as conn:
        d = conn.execute(
            "SELECT d.*, u.telegram_id, u.referred_by, u.referral_rewarded FROM deposits d JOIN users u ON d.user_id = u.id WHERE d.id = ?",
            (deposit_id,),
        ).fetchone()

        if not d or d["status"] != "pending":
            await update.message.reply_text("❌ الإيداع غير موجود أو تمت معالجته.")
            return ConversationHandler.END

        conn.execute(
            "UPDATE deposits SET status='approved', amount=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
            (amount, deposit_id),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id=?",
            (amount, d["user_id"]),
        )

        referral_reward_given = False
        if d["referred_by"] and not d["referral_rewarded"]:
            first_approved = conn.execute(
                "SELECT COUNT(*) as cnt FROM deposits WHERE user_id=? AND status='approved' AND id!=?",
                (d["user_id"], deposit_id),
            ).fetchone()["cnt"]
            if first_approved == 0:
                conn.execute(
                    "UPDATE users SET balance = balance + 0.50 WHERE id=?", (d["referred_by"],)
                )
                conn.execute(
                    "UPDATE users SET referral_rewarded=1 WHERE id=?", (d["user_id"],)
                )
                referral_reward_given = True
                referrer = conn.execute(
                    "SELECT telegram_id FROM users WHERE id=?", (d["referred_by"],)
                ).fetchone()

    await update.message.reply_text(
        f"✅ تم قبول الإيداع #{deposit_id}\nالمبلغ: ${amount:.2f}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 للإيداعات", callback_data="admin_deposits")]]
        ),
    )

    try:
        await context.bot.send_message(
            chat_id=d["telegram_id"],
            text=f"✅ *تم قبول إيداعك!*\n\nالمبلغ المُضاف: ${amount:.2f}",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    if referral_reward_given and referrer:
        try:
            await context.bot.send_message(
                chat_id=referrer["telegram_id"],
                text="🎉 *مكافأة الإحالة!*\n\nصديقك أكمل أول إيداع ناجح!\nتم إضافة $0.50 إلى رصيدك. 🎁",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    context.user_data.clear()
    return ConversationHandler.END
