import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, get_setting
from blockchain import verify_tx

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))

DEPOSIT_NETWORK, DEPOSIT_HASH = range(2)
WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 12)


async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 إيداع", callback_data="deposit_start"),
            InlineKeyboardButton("📤 سحب", callback_data="withdraw_start"),
        ],
        [InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")],
    ])

    await query.edit_message_text(
        f"💰 *محفظتك*\n\n"
        f"الرصيد الحالي: *${db_user['balance']:.2f}*\n\n"
        f"الحد الأدنى للإيداع: $5\n"
        f"الحد الأدنى للسحب: $10",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 USDT TRC-20 (Tron)", callback_data="deposit_trc20"),
            InlineKeyboardButton("🟡 USDT BEP-20 (BNB)", callback_data="deposit_bep20"),
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="wallet")],
    ])
    await query.edit_message_text(
        "📥 *طلب إيداع*\n\nاختر الشبكة:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def deposit_network_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    network = "TRC-20" if query.data == "deposit_trc20" else "BEP-20"
    context.user_data["deposit_network"] = network

    key = "trc20_address" if network == "TRC-20" else "bep20_address"
    address = get_setting(key)

    if not address:
        await query.edit_message_text(
            "⚠️ عنوان المحفظة غير متوفر حالياً. تواصل مع الأدمن.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="wallet")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"📥 *إيداع عبر USDT {network}*\n\n"
        f"أرسل USDT إلى هذا العنوان:\n`{address}`\n\n"
        f"⚠️ الحد الأدنى: *$5*\n\n"
        f"بعد التحويل، أرسل رقم المعاملة (Transaction Hash) أو صورة الإثبات:",
        parse_mode="Markdown",
    )
    return DEPOSIT_HASH


async def deposit_hash_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user_by_telegram_id(user.id)
    network = context.user_data.get("deposit_network", "TRC-20")

    tx_hash = None
    proof_file_id = None

    if update.message.text:
        tx_hash = update.message.text.strip()
    elif update.message.photo:
        proof_file_id = update.message.photo[-1].file_id
    elif update.message.document:
        proof_file_id = update.message.document.file_id
    else:
        await update.message.reply_text("❌ أرسل رقم المعاملة أو صورة الإثبات.")
        return DEPOSIT_HASH

    # ── التحقق التلقائي من الهاش عبر البلوكشين ──
    verified_amount = 0.0
    verify_status = ""
    verify_icon = ""

    if tx_hash:
        checking_msg = await update.message.reply_text("🔍 جاري التحقق من العملية على البلوكشين...")
        result = await verify_tx(network, tx_hash)
        try:
            await checking_msg.delete()
        except Exception:
            pass

        if result["ok"]:
            verified_amount = result["amount"]
            confirmed = result.get("confirmed", False)
            if confirmed:
                verify_status = f"✅ عملية مؤكدة | المبلغ: ${verified_amount:.2f} USDT"
                verify_icon = "✅"
            else:
                verify_status = f"⏳ عملية معلقة (غير مؤكدة بعد) | المبلغ: ${verified_amount:.2f} USDT"
                verify_icon = "⏳"
        else:
            verify_status = f"⚠️ {result['error']}"
            verify_icon = "⚠️"
            await update.message.reply_text(
                f"⚠️ *تنبيه التحقق:*\n{result['error']}\n\n"
                f"سيتم إرسال الطلب للمراجعة اليدوية من الأدمن.",
                parse_mode="Markdown",
            )

    user_amount = context.user_data.get("deposit_amount", 0)
    final_amount = verified_amount if verified_amount > 0 else user_amount

    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO deposits (user_id, network, tx_hash, proof_file_id, amount) VALUES (?, ?, ?, ?, ?)",
            (db_user["id"], network, tx_hash, proof_file_id, final_amount),
        )
        deposit_id = cursor.lastrowid

    await update.message.reply_text(
        f"📥 *تم استلام طلب الإيداع #{deposit_id}*\n\n"
        f"🌐 الشبكة: {network}\n"
        f"🔗 الهاش: `{tx_hash or 'صورة إثبات'}`\n"
        f"🔍 التحقق: {verify_status or 'سيُراجَع يدوياً'}\n\n"
        f"سيقوم الأدمن بمراجعة الطلب وتأكيده قريباً.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )

    try:
        proof_text = f"`{tx_hash}`" if tx_hash else "📎 صورة إثبات"
        admin_text = (
            f"📥 *طلب إيداع جديد #{deposit_id}* {verify_icon}\n\n"
            f"👤 المستخدم: {user.full_name} (@{user.username or 'بدون يوزر'})\n"
            f"🌐 الشبكة: {network}\n"
            f"🔗 الهاش: {proof_text}\n"
            f"💵 المبلغ: ${final_amount:.2f} USDT\n"
            f"🔍 التحقق: {verify_status or 'مرسل بصورة إثبات — راجع يدوياً'}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ قبول", callback_data=f"admin_approve_deposit_{deposit_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_deposit_{deposit_id}"),
                ]
            ]),
        )
        if proof_file_id:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=proof_file_id)
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END


async def deposit_amount_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["deposit_step"] = "amount"
    await query.edit_message_text(
        "📥 أدخل المبلغ الذي تريد إيداعه (بالدولار):\n\n⚠️ الحد الأدنى: $5",
    )
    return DEPOSIT_NETWORK


async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغاً صحيحاً.")
        return DEPOSIT_NETWORK

    if amount < 5:
        await update.message.reply_text("❌ الحد الأدنى للإيداع هو $5.")
        return DEPOSIT_NETWORK

    context.user_data["deposit_amount"] = amount

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 USDT TRC-20 (Tron)", callback_data="deposit_trc20"),
            InlineKeyboardButton("🟡 USDT BEP-20 (BNB)", callback_data="deposit_bep20"),
        ],
    ])
    await update.message.reply_text(
        f"💵 المبلغ: ${amount:.2f}\n\nاختر الشبكة:",
        reply_markup=keyboard,
    )
    return DEPOSIT_NETWORK


async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < 10:
        await query.edit_message_text(
            f"❌ رصيدك غير كافٍ للسحب.\n"
            f"الحد الأدنى للسحب: $10\n"
            f"رصيدك الحالي: ${db_user['balance']:.2f}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data="wallet")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"📤 *طلب سحب*\n\n"
        f"رصيدك: ${db_user['balance']:.2f}\n"
        f"الحد الأدنى: $10\n\n"
        f"أرسل عنوان محفظتك (USDT):",
        parse_mode="Markdown",
    )
    return WITHDRAW_ADDRESS


async def withdraw_address_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_address"] = update.message.text.strip()
    await update.message.reply_text("💵 أدخل المبلغ المراد سحبه:")
    return WITHDRAW_AMOUNT


async def withdraw_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user_by_telegram_id(user.id)

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغاً صحيحاً.")
        return WITHDRAW_AMOUNT

    if amount < 10:
        await update.message.reply_text("❌ الحد الأدنى للسحب هو $10.")
        return WITHDRAW_AMOUNT

    if amount > db_user["balance"]:
        await update.message.reply_text(
            f"❌ رصيدك غير كافٍ. رصيدك: ${db_user['balance']:.2f}"
        )
        return WITHDRAW_AMOUNT

    wallet_address = context.user_data.get("withdraw_address")

    with db() as conn:
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE telegram_id = ?",
            (amount, user.id),
        )
        cursor = conn.execute(
            "INSERT INTO withdrawals (user_id, amount, wallet_address) VALUES (?, ?, ?)",
            (db_user["id"], amount, wallet_address),
        )
        withdrawal_id = cursor.lastrowid

    await update.message.reply_text(
        f"✅ تم إرسال طلب السحب!\n"
        f"رقم الطلب: #{withdrawal_id}\n"
        f"المبلغ: ${amount:.2f}\n"
        f"سيتم معالجته من الأدمن قريباً.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📤 *طلب سحب جديد #{withdrawal_id}*\n\n"
                 f"👤 المستخدم: {user.full_name} (@{user.username})\n"
                 f"💵 المبلغ: ${amount:.2f}\n"
                 f"📍 العنوان: `{wallet_address}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ قبول", callback_data=f"admin_approve_withdrawal_{withdrawal_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_withdrawal_{withdrawal_id}"),
                ]
            ]),
        )
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ تم الإلغاء.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 الرئيسية", callback_data="main_menu")]]
        ),
    )
    return ConversationHandler.END
