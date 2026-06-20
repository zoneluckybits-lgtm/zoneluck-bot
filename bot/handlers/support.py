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
    lang = get_user_lang(update.effective_user.id)

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

    # إرسال للأدمن
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📩 *رسالة دعم جديدة*\n\n"
                f"👤 المستخدم: {name} ({username})\n"
                f"🆔 Telegram ID: `{user.id}`\n\n"
                f"💬 *الرسالة:*\n{msg}"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"↩️ ردّ على {name}",
                    url=f"tg://user?id={user.id}"
                )]
            ]),
        )
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


async def support_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await support_menu.__wrapped__(update, context) if hasattr(support_menu, "__wrapped__") else await support_menu(update, context)
    return ConversationHandler.END
