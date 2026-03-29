#!/usr/bin/env python3
"""
KlinkerOblik — Telegram Bot for Construction Brigade Work Tracking
"""

import logging
from telegram.ext import Application, CommandHandler
from telegram.constants import ParseMode

from config import BOT_TOKEN
from database import init_db
from handlers.start import get_start_handler
from handlers.menu import get_menu_handler
from handlers.reports import get_reports_handlers
from handlers.brigades import get_brigades_handlers
from handlers.projects import get_projects_handlers
from handlers.rates import get_rates_handlers
from handlers.work_types import get_work_types_handlers
from handlers.clients import get_clients_handlers
from handlers.settings import get_settings_handlers
from handlers.work_entry import get_work_entry_handler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Initialize database after application starts."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")


async def help_command(update, context):
    """Handle /help command."""
    await update.message.reply_text(
        "🏗 *KlinkerOblik Bot*\n\n"
        "📝 /start — Реєстрація / Головне меню\n"
        "📊 Звіти — перегляд звітів за день/тиждень/місяць\n"
        "👷 Бригади — управління бригадами та працівниками\n"
        "🏗️ Об'єкти — управління об'єктами, будинками, елементами\n"
        "💰 Розцінки — налаштування ставок\n"
        "🔧 Типи робіт — додавання типів робіт\n"
        "⚙️ Налаштування — мова, валюта\n\n"
        "_Бот для обліку робіт будівельних бригад_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def error_handler(update, context):
    """Log errors."""
    logger.error(f"Update {update} caused error: {context.error}")


def main():
    """Start the bot."""
    logger.info("Starting KlinkerOblik Bot...")

    # Create application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    application.add_handler(get_start_handler())
    application.add_handler(get_menu_handler())
    application.add_handler(get_work_entry_handler())
    application.add_handler(CommandHandler("help", help_command))

    # Other handlers (lists)
    for handler in get_reports_handlers():
        application.add_handler(handler)
    for handler in get_brigades_handlers():
        application.add_handler(handler)
    for handler in get_projects_handlers():
        application.add_handler(handler)
    for handler in get_rates_handlers():
        application.add_handler(handler)
    for handler in get_work_types_handlers():
        application.add_handler(handler)
    for handler in get_clients_handlers():
        application.add_handler(handler)
    for handler in get_settings_handlers():
        application.add_handler(handler)

    # Error handler
    application.add_error_handler(error_handler)

    # Start polling
    logger.info("Bot started. Polling...")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
