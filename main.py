import os
import logging
import traceback
import threading
from typing import Dict, DefaultDict
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
    CallbackContext,
)
from aiohttp import web  # For Render health checks
from config import ITEMS, MESSAGES

# ——— Load config —————————————————————————————————————
load_dotenv()
BOT_TOKEN      = os.getenv('BOT_TOKEN')
PROVIDER_TOKEN = os.getenv('PROVIDER_TOKEN', '')
ADMIN_CHAT_IDS = [
    int(i) for i in os.getenv('ADMIN_CHAT_IDS', '').split(',') if i.strip().isdigit()
]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

STATS: Dict[str, DefaultDict[str, int]] = {'purchases': defaultdict(int)}

# ——— Telegram handlers —————————————————————————————————
def build_upgrade_keyboard() -> InlineKeyboardMarkup:
    kb = []
    for item_id, item in ITEMS.items():
        kb.append([InlineKeyboardButton(item['name'], callback_data=item_id)])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: CallbackContext) -> None:
    await update.message.reply_text(
        f"{MESSAGES['welcome']}\n\n",
        parse_mode='Markdown',
        reply_markup=build_upgrade_keyboard()
    )

async def upgrade(update: Update, ctx: CallbackContext) -> None:
    await update.message.reply_text("Choose an upgrade", reply_markup=build_upgrade_keyboard())

async def button_handler(update: Update, ctx: CallbackContext) -> None:
    q = update.callback_query
    if not q or not q.message:
        return
    await q.answer()
    item = ITEMS[q.data]
    await ctx.bot.send_invoice(
        chat_id=q.message.chat_id,
        title=item['name'],
        description=item['description'],
        payload=q.data,
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(item['name'], item['price'])],
        start_parameter="start"
    )

async def precheckout_callback(update: Update, ctx: CallbackContext) -> None:
    q = update.pre_checkout_query
    ok = q.invoice_payload in ITEMS
    await q.answer(ok=ok, error_message=None if ok else "Invalid payload")

async def successful_payment_callback(update: Update, ctx: CallbackContext) -> None:
    pay = update.message.successful_payment
    item_id = pay.invoice_payload
    user = update.effective_user
    STATS['purchases'][str(user.id)] += 1

    await update.message.reply_text(
        "🎉 Purchased Successfully!\n\n"
        "Your upgrade has been applied permanently.\n\n"
        "If your Mining Power does not increase within 6 hours, please contact support.",
        parse_mode='Markdown'
    )

    uname = f"@{user.username}" if user.username else user.first_name
    for admin_id in ADMIN_CHAT_IDS:
        await ctx.bot.send_message(
            chat_id=admin_id,
            text=(
                f"*New Purchase*\n"
                f"User: {uname} (`{user.id}`)\n"
                f"Pack: *{ITEMS[item_id]['name']}*\n"
                f"Cost: `{ITEMS[item_id]['price']} ⭐️`\n"
                f"Charge ID: `{pay.telegram_payment_charge_id}`"
            ),
            parse_mode='Markdown'
        )

async def error_handler(update: object, ctx: CallbackContext) -> None:
    logger.error(f"Exception in update {update}: {ctx.error}")
    traceback.print_exc()

# ——— Aiohttp health‑check ——————————————————————————————
async def health_check(request):
    return web.Response(text="OK", status=200)

def run_web():
    app = web.Application()
    app.add_routes([web.get('/', health_check)])
    port = int(os.getenv('PORT', 8080))
    web.run_app(app, host='0.0.0.0', port=port)

# ——— Main entrypoint ——————————————————————————————————
if __name__ == '__main__':
    # 1) Start the health‑check server in a daemon thread
    threading.Thread(target=run_web, daemon=True).start()

    # 2) Build and run the Telegram bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("upgrade", upgrade))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_error_handler(error_handler)

    logger.info("Bot and web server started. Entering polling loop.")
    application.run_polling()  # blocks here, no event‑loop conflicts
