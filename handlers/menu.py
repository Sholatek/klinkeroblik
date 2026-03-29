import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from utils.i18n import t
from utils.keyboards import main_menu_keyboard
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         send_new: bool = False) -> None:
    info = context.user_data.get("info")
    if not info:
        info = await get_user_info(update.effective_user.id)
        if not info:
            msg = update.effective_message or update.callback_query.message
            await msg.reply_text("⚠️ /start")
            return
        context.user_data["info"] = info

    lang = info["lang"]
    role = info["role"]
    text = t(lang, "welcome_back", name=info["name"]) + "\n\n" + t(lang, "menu.title")
    keyboard = main_menu_keyboard(lang, role)

    if send_new:
        msg = update.effective_message or update.callback_query.message
        await msg.reply_text(text, reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    if action == "main":
        await show_main_menu(update, context)
        return

    info = context.user_data.get("info")
    if not info:
        info = await get_user_info(update.effective_user.id)
        if not info:
            await query.edit_message_text("⚠️ /start")
            return
        context.user_data["info"] = info

    if action == "reports":
        from handlers.reports import show_reports_menu
        await show_reports_menu(update, context)
    elif action == "brigades":
        from handlers.brigades import show_brigades_menu
        await show_brigades_menu(update, context)
    elif action == "projects":
        from handlers.projects import show_projects_menu
        await show_projects_menu(update, context)
    elif action == "rates":
        from handlers.rates import show_rates_menu
        await show_rates_menu(update, context)
    elif action == "work_types":
        from handlers.work_types import show_work_types_menu
        await show_work_types_menu(update, context)
    elif action == "settings":
        from handlers.settings import show_settings
        await show_settings(update, context)
    elif action == "clients":
        from handlers.clients import show_clients_menu
        await show_clients_menu(update, context)


def get_menu_handler():
    return CallbackQueryHandler(menu_callback, pattern=r"^menu:(?!work$)")
