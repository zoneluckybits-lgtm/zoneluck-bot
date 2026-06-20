import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from utils import get_user_by_telegram_id, format_user_name, get_user_lang

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
SUPPORT_EMAIL = "zoneluckybits@gmail.com"
SUPPORT_MSG = 600


async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "📞 *خدمة العملاء — Zone Luck*\n\n"
        f"📧 البريد الإلكتروني:\n`{SUPPORT_EMAIL}`\n\n"
        "أو أرسل لنا رسالة مباشرة من هنا وسيصلك الرد قريباً 👇"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✉️ أرسل رسالة للدعم", callback_data="support_send")],
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
        ]),
    )


async def support_send_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "✏️ *اكتب رسالتك وأرسلها:*\n\n"
        "_سيصلك رد من فريق الدعم في أقرب وقت._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إلغاء", callback_data="support_menu")],
        ]),
    )
    return SUPPORT_MSG


async def support_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text.strip()
    db_user = get_user_by_telegram_id(user.id)
    name = format_user_name(dict(db_user)) if db_user else user.full_name or str(user.id)
    username = f"@{user.username}" if user.username else f"ID: {user.id}"

    # إرسال للأدمن — بدون رابط لحساب الزبون
    try:
        sent = await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📩 *رسالة دعم جديدة*\n\n"
                f"👤 المستخدم: {name} ({username})\n"
                f"🆔 ID: `{user.id}`\n\n"
                f"💬 *الرسالة:*\n{msg}\n\n"
                f"_↩️ للرد: استخدم زر Reply على هذه الرسالة وسيصل ردك للزبون تلقائياً_"
            ),
            parse_mode="Markdown",
        )
        # حفظ المراسلة: message_id الأدمن → telegram_id الزبون
        if "support_map" not in context.bot_data:
            context.bot_data["support_map"] = {}
        context.bot_data["support_map"][sent.message_id] = user.id
    except Exception:
        pass

    # تأكيد للمستخدم
    await update.message.reply_text(
        "✅ *تم إرسال رسالتك بنجاح!*\n\n"
        "سيتواصل معك فريق الدعم قريباً.\n\n"
        f"أو راسلنا مباشرة على:\n📧 `{SUPPORT_EMAIL}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
        ]),
    )
    return ConversationHandler.END


async def admin_support_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأدمن يضغط Reply على رسالة الدعم → البوت يرسل الرد للزبون بدون كشف هوية الأدمن"""
    message = update.message

    # تأكد أن المرسل هو الأدمن وأنها رد على رسالة
    if update.effective_user.id != ADMIN_ID:
        return
    if not message.reply_to_message:
        return

    replied_msg_id = message.reply_to_message.message_id
    support_map = context.bot_data.get("support_map", {})
    user_id = support_map.get(replied_msg_id)

    if not user_id:
        return  # ليست رداً على رسالة دعم

    reply_text = message.text.strip() if message.text else None
    if not reply_text:
        await message.reply_text("⚠️ يرجى إرسال نص فقط.")
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"📬 *رد من فريق الدعم — Zone Luck:*\n\n"
                f"{reply_text}\n\n"
                f"📧 للمزيد: `{SUPPORT_EMAIL}`"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
            ]),
        )
        await message.reply_text("✅ تم إرسال ردك للزبون بنجاح.")
        # إزالة المراسلة بعد الرد
        support_map.pop(replied_msg_id, None)
    except Exception as e:
        await message.reply_text(f"❌ فشل الإرسال: {e}")
