import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from sqlalchemy import select

from database import async_session
from models import Director, Worker
from utils.i18n import t
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

CURRENCIES = [("PLN", "zł"), ("EUR", "€"), ("UAH", "₴")]


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]

    buttons = [
        [InlineKeyboardButton(t(lang, "settings.language"), callback_data="set:lang")],
    ]
    if info["role"] == "director":
        buttons.append([InlineKeyboardButton(t(lang, "settings.currency"), callback_data="set:currency")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])

    # Get current settings
    async with async_session() as session:
        if info["role"] == "director":
            result = await session.execute(
                select(Director).where(Director.id == info["director_id"])
            )
            user = result.scalar_one()
        else:
            result = await session.execute(
                select(Worker).where(Worker.id == info["worker_id"])
            )
            user = result.scalar_one()

    lang_name = t(lang, "lang_name")
    curr = user.currency if info["role"] == "director" else "PLN"

    text = t(lang, "settings.current", language=lang_name, currency=curr)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(buttons)
        )


async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    current_lang = info["lang"]

    buttons = [
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="set_lang:uk")],
        [InlineKeyboardButton("🇵🇱 Polski", callback_data="set_lang:pl")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="set_lang:ru")],
        [InlineKeyboardButton(t(current_lang, "btn.back"), callback_data="menu:settings")],
    ]

    await query.edit_message_text(
        t(current_lang, "settings.language"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    new_lang = query.data.split(":")[1]

    async with async_session() as session:
        if info["role"] == "director":
            result = await session.execute(
                select(Director).where(Director.id == info["director_id"])
            )
            user = result.scalar_one()
        else:
            result = await session.execute(
                select(Worker).where(Worker.id == info["worker_id"])
            )
            user = result.scalar_one()

        user.language = new_lang
        await session.commit()

    info["lang"] = new_lang
    context.user_data["info"] = info

    await query.edit_message_text(t(new_lang, "settings.lang_changed"))
    from handlers.menu import show_main_menu
    await show_main_menu(update, context, send_new=True)


async def change_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]

    if info["role"] != "director":
        await query.edit_message_text(t(lang, "errors.no_permission"))
        return

    buttons = [[InlineKeyboardButton(f"{sym} — {code}", callback_data=f"set_curr:{code}")]
               for code, sym in CURRENCIES]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:settings")])

    await query.edit_message_text(
        t(lang, "settings.select_currency"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def currency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    new_currency = query.data.split(":")[1]

    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        director.currency = new_currency
        await session.commit()

    info["currency"] = new_currency
    context.user_data["info"] = info

    await query.edit_message_text(t(lang, "settings.currency_changed"))
    await show_settings(update, context)


def get_settings_handlers():
    return [
        CallbackQueryHandler(change_language, pattern=r"^set:lang$"),
        CallbackQueryHandler(language_selected, pattern=r"^set_lang:(uk|pl|ru)$"),
        CallbackQueryHandler(change_currency, pattern=r"^set:currency$"),
        CallbackQueryHandler(currency_selected, pattern=r"^set_curr:(PLN|EUR|UAH)$"),
    ]
