import logging
from decimal import Decimal, InvalidOperation

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select

from database import async_session
from models import WorkType
from utils.i18n import t, unit_label, currency_symbol
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

WT_ADD_NAME_UK, WT_ADD_NAME_PL, WT_ADD_NAME_RU = 500, 501, 502
WT_ADD_UNIT, WT_ADD_RATE = 503, 504

UNITS = [("m2", "м²/м²"), ("mp", "мп/mb"), ("h", "год/godz")]


async def show_work_types_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]

    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        curr_sym = currency_symbol(director.currency)

        result = await session.execute(
            select(WorkType).where(
                WorkType.director_id == info["director_id"],
                WorkType.is_active == True,
            ).order_by(WorkType.sort_order)
        )
        work_types = result.scalars().all()

    lines = [t(lang, "work_types_menu.list_title"), ""]
    buttons = []
    for wt in work_types:
        ul = unit_label(wt.unit, lang)
        lines.append(t(lang, "work_types_menu.type_line",
                       name=wt.get_name(lang), unit=ul,
                       rate=f"{wt.default_rate:.2f}", currency=curr_sym))
        buttons.append([InlineKeyboardButton(
            f"🗑 {wt.get_name(lang)}",
            callback_data=f"wt:deactivate:{wt.id}"
        )])

    buttons.append([InlineKeyboardButton(t(lang, "work_types_menu.add"), callback_data="wt:add")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def add_work_type_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    await query.edit_message_text(t(lang, "work_types_menu.enter_name_uk"))
    return WT_ADD_NAME_UK


async def add_name_uk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["wt_name_uk"] = update.message.text.strip()
    await update.message.reply_text(t(context.user_data["lang"], "work_types_menu.enter_name_pl"))
    return WT_ADD_NAME_PL


async def add_name_pl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["wt_name_pl"] = update.message.text.strip()
    await update.message.reply_text(t(context.user_data["lang"], "work_types_menu.enter_name_ru"))
    return WT_ADD_NAME_RU


async def add_name_ru(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["wt_name_ru"] = update.message.text.strip()
    buttons = [[InlineKeyboardButton(f"{u[0]} — {u[1]}", callback_data=f"wt:unit:{u[0]}")]
               for u in UNITS]
    await update.message.reply_text(
        t(context.user_data["lang"], "work_types_menu.select_unit"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WT_ADD_UNIT


async def add_unit_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["wt_unit"] = query.data.split(":")[2]
    lang = context.user_data["lang"]
    await query.edit_message_text(t(lang, "work_types_menu.enter_rate"))
    return WT_ADD_RATE


async def add_rate_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip().replace(",", ".")

    try:
        rate = Decimal(text)
        if rate < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await update.message.reply_text("⚠️ Введіть число")
        return WT_ADD_RATE

    async with async_session() as session:
        result = await session.execute(
            select(WorkType).order_by(WorkType.sort_order.desc()).limit(1)
        )
        last_wt = result.scalar_one_or_none()
        next_order = (last_wt.sort_order + 1) if last_wt else 1

        wt = WorkType(
            director_id=info["director_id"],
            name_uk=context.user_data["wt_name_uk"],
            name_pl=context.user_data["wt_name_pl"],
            name_ru=context.user_data["wt_name_ru"],
            unit=context.user_data["wt_unit"],
            default_rate=rate,
            sort_order=next_order,
        )
        session.add(wt)
        await session.commit()

    await update.message.reply_text(
        t(lang, "work_types_menu.created", name=context.user_data["wt_name_uk"])
    )
    await show_work_types_menu(update, context)
    return ConversationHandler.END


async def deactivate_work_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    wt_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(WorkType).where(WorkType.id == wt_id))
        wt = result.scalar_one()
        wt.is_active = False
        await session.commit()
        name = wt.get_name(lang)

    await query.edit_message_text(t(lang, "work_types_menu.deactivated", name=name))
    await show_work_types_menu(update, context)


def get_work_types_handlers():
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_work_type_start, pattern=r"^wt:add$")],
        states={
            WT_ADD_NAME_UK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name_uk)],
            WT_ADD_NAME_PL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name_pl)],
            WT_ADD_NAME_RU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name_ru)],
            WT_ADD_UNIT: [CallbackQueryHandler(add_unit_selected, pattern=r"^wt:unit:")],
            WT_ADD_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rate_entered)],
        },
        fallbacks=[],
        per_message=False,
    )

    return [
        add_conv,
        CallbackQueryHandler(deactivate_work_type, pattern=r"^wt:deactivate:\d+$"),
    ]
