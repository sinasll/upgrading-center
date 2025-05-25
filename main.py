import os
import logging
import traceback
from typing import Dict, Any, DefaultDict
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
from aiohttp import web  # For Render compatibility
from config import ITEMS, MESSAGES

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_IDS = [
    int(id.strip()) for id in os.getenv('ADMIN_CHAT_IDS', '').split(',') if id.strip().isdigit()
]

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store statistics
STATS: Dict[str, DefaultDict[str, int]] = {
    'purchases': defaultdict(int)
}

def build_upgrade_keyboard() -> InlineKeyboardMarkup:
    """Helper to build the inline keyboard for all ITEMS."""
    keyboard = []
    for item_id, item in ITEMS.items():
        keyboard.append([
            InlineKeyboardButton(
                item['name'],
                callback_data=item_id
            )
        ])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: CallbackContext) -> None:
    """Handle /start command - show the welcome message + upgrades."""
    text = f"{MESSAGES['welcome']}\n\n"
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=build_upgrade_keyboard()
    )

async def upgrade(update: Update, context: CallbackContext) -> None:
    """Handle /upgrade command - show available mining power upgrades."""
    await update.message.reply_text(
        "Choose an upgrade",
        reply_markup=build_upgrade_keyboard()
    )

async def button_handler(update: Update, context: CallbackContext) -> None:
    """Handle button clicks for item selection."""
    query = update.callback_query
    if not query or not query.message:
        return

    try:
        await query.answer()
        item_id = query.data
        item = ITEMS[item_id]

        if not isinstance(query.message, Message):
            return

        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=item['name'],
            description=item['description'],
            payload=item_id,
            provider_token=os.getenv("PROVIDER_TOKEN", ""),
            currency="XTR",
            prices=[LabeledPrice(item['name'], item['price'])],
            start_parameter="start_parameter"
        )

    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        await query.message.reply_text("Something went wrong while processing your request.")

async def precheckout_callback(update: Update, context: CallbackContext) -> None:
    """Handle pre-checkout queries."""
    query = update.pre_checkout_query
    if query.invoice_payload in ITEMS:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Something went wrong...")

async def successful_payment_callback(update: Update, context: CallbackContext) -> None:
    """Handle successful payments and inform about permanent upgrade timeline."""
    payment = update.message.successful_payment
    item_id = payment.invoice_payload
    item = ITEMS[item_id]
    user_id = update.effective_user.id

    STATS['purchases'][str(user_id)] += 1

    logger.info(
        f"Successful payment from user {user_id} for item {item_id} "
        f"(charge_id: {payment.telegram_payment_charge_id})"
    )

    await update.message.reply_text(
        "🎉 Purchased Successfully!\n"
        "\n"
        "Your upgrade has been applied permanently.\n"
        "\n"
        "If your Mining Power does not increase within 6 hours, please contact our support team.\n"
        "\n"
        "You will receive a full refund of your stars, and your Mining Power will be upgraded to the level of the pack you purchased completely free of charge.\n"
        "\n"
        "We are committed to ensuring your satisfaction and a seamless experience.",
        parse_mode='Markdown'
    )

    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    for admin_id in ADMIN_CHAT_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"*New Purchase*\n"
                f"User: {username} (`{user.id}`)\n"
                f"Pack: *{item['name']}*\n"
                f"Cost: `{item['price']} ⭐️`\n"
                f"Charge ID: `{payment.telegram_payment_charge_id}`"
            ),
            parse_mode='Markdown'
        )

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log and notify of unexpected errors."""
    logger.error(f"Update {update} caused error {context.error}")
    traceback.print_exc()

async def health_check(request):
    """Render.com health check endpoint."""
    return web.Response(text="OK", status=200)

async def main() -> None:
    """Start the bot and web server."""
    try:
        application = Application.builder().token(BOT_TOKEN).build()

        # Add bot handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("upgrade", upgrade))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
        application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
        application.add_error_handler(error_handler)

        # Setup aiohttp app for Render health checks
        web_app = web.Application()
        web_app.add_routes([web.get("/", health_check)])

        # Start both Telegram bot polling and web app
        await application.initialize()
        await application.start()
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
        await site.start()

        logger.info("Bot and web server started. Press Ctrl+C to stop.")
        await application.updater.start_polling()
        await application.run_polling()

    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
