import os
import sys
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from database import init_db
from handlers.common import start, menu_callback, my_stats, change_language, set_language
from handlers.wallet import (
    wallet_menu, deposit_start, deposit_network_selected,
    deposit_hash_received, deposit_amount_received,
    withdraw_start, withdraw_address_received,
    withdraw_amount_received, cancel,
    DEPOSIT_NETWORK, DEPOSIT_HASH, DEPOSIT_AMOUNT_INPUT, WITHDRAW_ADDRESS, WITHDRAW_AMOUNT,
)
from handlers.referral import referral_menu
from handlers.matches import (
    matches_menu, show_matches, show_bet_types, bet_type_selected,
    bet_prediction_received, cancel_bet, cancel_bet_callback, BET_PREDICTION,
)
from handlers.lottery import lottery_menu, lottery_buy, lottery_confirm
from handlers.admin import (
    admin_panel, admin_users, admin_user_detail,
    admin_deposits, admin_deposit_detail,
    admin_approve_deposit, admin_reject_deposit, admin_deposit_amount_input,
    admin_withdrawals, admin_withdrawal_detail,
    admin_approve_withdrawal, admin_reject_withdrawal,
    admin_matches, admin_add_match_start, admin_add_match_home,
    admin_add_match_away, admin_add_match_time,
    admin_match_detail, admin_enter_result_start,
    admin_result_score, admin_result_yellow, admin_result_red, admin_result_penalty,
    admin_wallets, admin_set_trc20_start, admin_set_trc20,
    admin_set_bep20_start, admin_set_bep20,
    admin_lottery, admin_draw_lottery_start,
    admin_lottery_first, admin_lottery_second, admin_lottery_third,
    admin_lottery_cancel,
    admin_cancel_to_matches, admin_cancel_to_wallets,
    admin_cancel,
    admin_sync_matches,
    admin_edit_match_start, admin_edit_match_home, admin_edit_match_away, admin_edit_match_time,
    admin_delete_match, admin_confirm_delete_match,
    admin_finance, admin_fin_dep_log, admin_fin_wd_log, admin_fin_bets_log, admin_fin_won_log,
    ADMIN_SET_TRC20, ADMIN_SET_BEP20,
    ADMIN_ADD_MATCH_HOME, ADMIN_ADD_MATCH_AWAY, ADMIN_ADD_MATCH_TIME,
    ADMIN_RESULT_SCORE, ADMIN_RESULT_YELLOW, ADMIN_RESULT_RED, ADMIN_RESULT_PENALTY,
    ADMIN_LOTTERY_FIRST, ADMIN_LOTTERY_SECOND, ADMIN_LOTTERY_THIRD,
    ADMIN_EDIT_MATCH_HOME, ADMIN_EDIT_MATCH_AWAY, ADMIN_EDIT_MATCH_TIME,
)
from handlers.deposit_amount import (
    admin_deposit_enter_amount_start, admin_deposit_amount_received,
    DEPOSIT_AMOUNT_STATE,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def _start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info(f"Health server listening on port {port}")
    server.serve_forever()


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        sys.exit(1)

    init_db()
    logger.info("Database initialized.")

    app = Application.builder().token(token).build()

    deposit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(deposit_start, pattern="^deposit_start$")],
        states={
            DEPOSIT_NETWORK: [
                CallbackQueryHandler(deposit_network_selected, pattern="^deposit_(trc20|bep20)$"),
            ],
            DEPOSIT_HASH: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, deposit_hash_received),
            ],
            DEPOSIT_AMOUNT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount_received),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^wallet$"),
        ],
        per_message=False,
        allow_reentry=True,
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_start, pattern="^withdraw_start$")],
        states={
            WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_address_received)],
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    bet_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bet_type_selected, pattern="^bettype_")],
        states={
            BET_PREDICTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bet_prediction_received),
                CallbackQueryHandler(cancel_bet_callback, pattern="^cancel_bet$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_bet),
            CallbackQueryHandler(cancel_bet_callback, pattern="^cancel_bet$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
        allow_reentry=True,
    )

    _cancel_matches = CallbackQueryHandler(admin_cancel_to_matches, pattern="^admin_cancel_to_matches$")
    _cancel_wallets = CallbackQueryHandler(admin_cancel_to_wallets, pattern="^admin_cancel_to_wallets$")

    admin_wallet_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_set_trc20_start, pattern="^admin_set_trc20$"),
            CallbackQueryHandler(admin_set_bep20_start, pattern="^admin_set_bep20$"),
        ],
        states={
            ADMIN_SET_TRC20: [_cancel_wallets, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_trc20)],
            ADMIN_SET_BEP20: [_cancel_wallets, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_bep20)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
    )

    admin_match_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_match_start, pattern="^admin_add_match$")],
        states={
            ADMIN_ADD_MATCH_HOME: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_match_home)],
            ADMIN_ADD_MATCH_AWAY: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_match_away)],
            ADMIN_ADD_MATCH_TIME: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_match_time)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
    )

    admin_edit_match_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_match_start, pattern="^admin_edit_match_\\d+$")],
        states={
            ADMIN_EDIT_MATCH_HOME: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_match_home)],
            ADMIN_EDIT_MATCH_AWAY: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_match_away)],
            ADMIN_EDIT_MATCH_TIME: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_match_time)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
        allow_reentry=True,
    )

    admin_result_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_enter_result_start, pattern="^admin_enter_result_")],
        states={
            ADMIN_RESULT_SCORE:   [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_result_score)],
            ADMIN_RESULT_YELLOW:  [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_result_yellow)],
            ADMIN_RESULT_RED:     [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_result_red)],
            ADMIN_RESULT_PENALTY: [_cancel_matches, MessageHandler(filters.TEXT & ~filters.COMMAND, admin_result_penalty)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
        allow_reentry=True,
    )

    _lottery_cancel_handler = CallbackQueryHandler(admin_lottery_cancel, pattern="^admin_lottery_cancel$")
    admin_lottery_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_draw_lottery_start, pattern="^admin_draw_lottery$")],
        states={
            ADMIN_LOTTERY_FIRST: [
                _lottery_cancel_handler,
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lottery_first),
            ],
            ADMIN_LOTTERY_SECOND: [
                _lottery_cancel_handler,
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lottery_second),
            ],
            ADMIN_LOTTERY_THIRD: [
                _lottery_cancel_handler,
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lottery_third),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
        allow_reentry=True,
    )

    admin_deposit_amount_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_deposit_enter_amount_start, pattern="^admin_dep_amount_")],
        states={
            DEPOSIT_AMOUNT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_deposit_amount_received)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_deposit_amount_input), group=10)
    app.add_handler(deposit_conv)
    app.add_handler(withdraw_conv)
    app.add_handler(bet_conv)
    app.add_handler(admin_wallet_conv)
    app.add_handler(admin_match_conv)
    app.add_handler(admin_edit_match_conv)
    app.add_handler(admin_result_conv)
    app.add_handler(admin_lottery_conv)
    app.add_handler(admin_deposit_amount_conv)

    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(my_stats, pattern="^my_stats$"))
    app.add_handler(CallbackQueryHandler(change_language, pattern="^change_language$"))
    app.add_handler(CallbackQueryHandler(set_language, pattern="^set_lang_(ar|en)$"))
    app.add_handler(CallbackQueryHandler(wallet_menu, pattern="^wallet$"))
    app.add_handler(CallbackQueryHandler(matches_menu, pattern="^matches_menu$"))
    app.add_handler(CallbackQueryHandler(show_matches, pattern="^matches_(today|week|all)$"))
    app.add_handler(CallbackQueryHandler(show_bet_types, pattern="^bet_match_"))
    app.add_handler(CallbackQueryHandler(referral_menu, pattern="^referral$"))
    app.add_handler(CallbackQueryHandler(lottery_menu, pattern="^lottery_menu$"))
    app.add_handler(CallbackQueryHandler(lottery_buy, pattern="^lottery_buy$"))
    app.add_handler(CallbackQueryHandler(lottery_confirm, pattern="^lottery_confirm$"))

    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_user_detail, pattern="^admin_user_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_deposits, pattern="^admin_deposits$"))
    app.add_handler(CallbackQueryHandler(admin_deposit_detail, pattern="^admin_dep_detail_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_approve_deposit, pattern="^admin_approve_deposit_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_reject_deposit, pattern="^admin_reject_deposit_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_withdrawals, pattern="^admin_withdrawals$"))
    app.add_handler(CallbackQueryHandler(admin_withdrawal_detail, pattern="^admin_wd_detail_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_approve_withdrawal, pattern="^admin_approve_(wd|withdrawal)_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_reject_withdrawal, pattern="^admin_reject_(wd|withdrawal)_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_matches, pattern="^admin_matches$"))
    app.add_handler(CallbackQueryHandler(admin_sync_matches, pattern="^admin_sync_matches$"))
    app.add_handler(CallbackQueryHandler(admin_match_detail, pattern="^admin_match_detail_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_match, pattern="^admin_delete_match_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_delete_match, pattern="^admin_confirm_delete_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_wallets, pattern="^admin_wallets$"))
    app.add_handler(CallbackQueryHandler(admin_lottery, pattern="^admin_lottery$"))
    app.add_handler(CallbackQueryHandler(admin_finance, pattern="^admin_finance$"))
    app.add_handler(CallbackQueryHandler(admin_fin_dep_log, pattern="^admin_fin_dep_log$"))
    app.add_handler(CallbackQueryHandler(admin_fin_wd_log, pattern="^admin_fin_wd_log$"))
    app.add_handler(CallbackQueryHandler(admin_fin_bets_log, pattern="^admin_fin_bets_log$"))
    app.add_handler(CallbackQueryHandler(admin_fin_won_log, pattern="^admin_fin_won_log$"))

    async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()

    app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))

    # شغّل خادم الصحة في الإنتاج فقط (مطلوب لـ Replit deployment)
    if os.environ.get("REPLIT_DEPLOYMENT"):
        health_thread = threading.Thread(target=_start_health_server, daemon=True)
        health_thread.start()

    logger.info("Zone Luck Bot is starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
