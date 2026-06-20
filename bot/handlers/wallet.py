import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from utils import get_user_by_telegram_id, get_setting, get_user_lang
from blockchain import verify_tx
from lang import t

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))

DEPOSIT_NETWORK, DEPOSIT_HASH, DEPOSIT_AMOUNT_INPUT = range(3)
WITHDRAW_ADDRESS, WITHDRAW_AMOUNT = range(10, 12)


async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("btn_deposit", lang), callback_data="deposit_start"),
            InlineKeyboardButton(t("btn_withdraw", lang), callback_data="withdraw_start"),
        ],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")],
    ])

    await query.edit_message_text(
        t("wallet_title", lang, balance=db_user["balance"]),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(query.from_user.id)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔵 USDT TRC-20 (Tron)", callback_data="deposit_trc20"),
            InlineKeyboardButton("🟡 USDT BEP-20 (BNB)", callback_data="deposit_bep20"),
        ],
        [InlineKeyboardButton(t("btn_back_short", lang), callback_data="wallet")],
    ])
    await query.edit_message_text(
        t("deposit_title", lang),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return DEPOSIT_NETWORK


async def deposit_network_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(query.from_user.id)

    network = "TRC-20" if query.data == "deposit_trc20" else "BEP-20"
    context.user_data["deposit_network"] = network

    key = "trc20_address" if network == "TRC-20" else "bep20_address"
    address = get_setting(key)

    if not address:
        await query.edit_message_text(
            t("deposit_no_address", lang),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="wallet")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        t("deposit_instructions", lang, network=network, address=address),
        parse_mode="Markdown",
    )
    return DEPOSIT_HASH


async def deposit_hash_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الخطوة 1: استقبال رقم العملية أو الإثبات، ثم سؤال المستخدم عن المبلغ."""
    user = update.effective_user
    lang = get_user_lang(user.id)
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
        await update.message.reply_text(t("deposit_invalid_hash", lang))
        return DEPOSIT_HASH

    # حفظ الإثبات مؤقتاً
    context.user_data["deposit_tx_hash"] = tx_hash
    context.user_data["deposit_proof_file_id"] = proof_file_id

    # التحقق التلقائي لو في TX hash
    verified_amount = 0.0
    verify_hint = ""
    if tx_hash:
        checking_msg = await update.message.reply_text(t("deposit_verifying", lang))
        result = await verify_tx(network, tx_hash)
        try:
            await checking_msg.delete()
        except Exception:
            pass
        if result["ok"]:
            verified_amount = result["amount"]
            verify_hint = f" (تم الكشف تلقائياً: ${verified_amount:.2f})"
        context.user_data["deposit_verified_amount"] = verified_amount

    await update.message.reply_text(
        f"💵 كم المبلغ الذي أرسلته بالدولار (USDT)؟{verify_hint}\n\nأدخل الرقم فقط، مثال: 10",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")]]
        ),
    )
    return DEPOSIT_AMOUNT_INPUT


async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الخطوة 2: استقبال المبلغ، حفظ الطلب وإشعار الأدمن."""
    user = update.effective_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)
    network = context.user_data.get("deposit_network", "TRC-20")
    tx_hash = context.user_data.get("deposit_tx_hash")
    proof_file_id = context.user_data.get("deposit_proof_file_id")
    verified_amount = context.user_data.get("deposit_verified_amount", 0.0)

    try:
        user_amount = float(update.message.text.strip().replace(",", "."))
        if user_amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً أكبر من صفر، مثال: 10")
        return DEPOSIT_AMOUNT_INPUT

    # استخدم المبلغ المتحقق لو أكبر من المُدخل، وإلا استخدم ما أدخله المستخدم
    final_amount = max(verified_amount, user_amount)
    verify_icon = "✅" if verified_amount > 0 else "👤"
    verify_status = f"تحقق تلقائي: ${verified_amount:.2f}" if verified_amount > 0 else f"أدخله المستخدم: ${user_amount:.2f}"

    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO deposits (user_id, network, tx_hash, proof_file_id, amount) VALUES (?, ?, ?, ?, ?)",
            (db_user["id"], network, tx_hash, proof_file_id, final_amount),
        )
        deposit_id = cursor.lastrowid

    await update.message.reply_text(
        t("deposit_pending", lang),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )

    proof_text = tx_hash if tx_hash else "صورة إثبات"
    admin_text = (
        f"📥 طلب إيداع جديد #{deposit_id} {verify_icon}\n\n"
        f"👤 {user.full_name} (@{user.username or 'no username'})\n"
        f"🌐 الشبكة: {network}\n"
        f"🔗 الإثبات: {proof_text}\n"
        f"💵 المبلغ: ${final_amount:.2f} USDT\n"
        f"🔍 {verify_status}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ قبول", callback_data=f"admin_approve_deposit_{deposit_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_deposit_{deposit_id}"),
                ]
            ]),
        )
    except Exception:
        pass
    if proof_file_id:
        try:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=proof_file_id)
        except Exception:
            pass

    context.user_data.clear()
    return ConversationHandler.END


async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    if db_user["balance"] < 10:
        await query.edit_message_text(
            t("withdraw_insufficient", lang, balance=db_user["balance"]),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("btn_back_short", lang), callback_data="wallet")]]
            ),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        t("withdraw_start", lang, balance=db_user["balance"]),
        parse_mode="Markdown",
    )
    return WITHDRAW_ADDRESS


async def withdraw_address_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    db_user = get_user_by_telegram_id(update.effective_user.id)
    address = update.message.text.strip()
    context.user_data["withdraw_address"] = address

    await update.message.reply_text(
        t("withdraw_enter_amount", lang, address=address, balance=db_user["balance"]),
        parse_mode="Markdown",
    )
    return WITHDRAW_AMOUNT


async def withdraw_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_lang(user.id)
    db_user = get_user_by_telegram_id(user.id)

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("withdraw_invalid_amount", lang))
        return WITHDRAW_AMOUNT

    if amount < 10:
        await update.message.reply_text(t("withdraw_min_error", lang))
        return WITHDRAW_AMOUNT

    if amount > db_user["balance"]:
        await update.message.reply_text(t("withdraw_insufficient", lang, balance=db_user["balance"]))
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
        t("withdraw_success", lang, amount=amount),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📤 طلب سحب جديد #{withdrawal_id}\n\n"
                f"👤 {user.full_name} (@{user.username or 'no username'})\n"
                f"💵 ${amount:.2f} USDT\n"
                f"📍 {wallet_address}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ قبول", callback_data=f"admin_approve_wd_{withdrawal_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_wd_{withdrawal_id}"),
                ]
            ]),
        )
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text(
        t("cancelled", lang),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_back", lang), callback_data="main_menu")]]
        ),
    )
    return ConversationHandler.END
