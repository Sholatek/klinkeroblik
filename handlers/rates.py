import logging
from decimal import Decimal, InvalidOperation

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select

from database import async_session
from models import WorkType, ProjectRate, Project, Director
from utils.i18n import t, unit_label, currency_symbol
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

RT_EDIT_VALUE = 400


async def show_rates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]

    buttons = [
        [InlineKeyboardButton(t(lang, "rates.edit_default"), callback_data="rt:defaults")],
        [InlineKeyboardButton(t(lang, "rates.edit_project"), callback_data="rt:by_project")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")],
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            t(lang, "rates.title"), reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            t(lang, "rates.title"), reply_markup=InlineKeyboardMarkup(buttons)
        )


async def show_default_rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
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

    lines = [t(lang, "rates.default_rates"), ""]
    buttons = []
    for wt in work_types:
        ul = unit_label(wt.unit, lang)
        lines.append(t(lang, "rates.rate_line",
                       work_type=wt.get_name(lang),
                       rate=f"{wt.default_rate:.2f}",
                       currency=curr_sym, unit=ul))
        buttons.append([InlineKeyboardButton(
            f"✏️ {wt.get_name(lang)}",
            callback_data=f"rt:edit_def:{wt.id}"
        )])

    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:rates")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def edit_default_rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    wt_id = int(query.data.split(":")[2])
    context.user_data["rt_wt_id"] = wt_id
    context.user_data["rt_mode"] = "default"

    async with async_session() as session:
        result = await session.execute(select(WorkType).where(WorkType.id == wt_id))
        wt = result.scalar_one()
        ul = unit_label(wt.unit, lang)

    await query.edit_message_text(
        t(lang, "rates.enter_rate", work_type=wt.get_name(lang), unit=ul)
    )
    return RT_EDIT_VALUE


async def show_project_rates_selector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]

    async with async_session() as session:
        result = await session.execute(
            select(Project).where(
                Project.director_id == info["director_id"],
                Project.is_active == True,
                Project.is_archived == False,
            ).order_by(Project.name)
        )
        projects = result.scalars().all()

    buttons = [[InlineKeyboardButton(p.name, callback_data=f"rt:proj:{p.id}")]
               for p in projects]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:rates")])

    await query.edit_message_text(
        t(lang, "rates.select_project"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def show_project_rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])
    context.user_data["rt_project_id"] = project_id

    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        curr_sym = currency_symbol(director.currency)

        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()

        result = await session.execute(
            select(WorkType).where(
                WorkType.director_id == info["director_id"],
                WorkType.is_active == True,
            ).order_by(WorkType.sort_order)
        )
        work_types = result.scalars().all()

        result = await session.execute(
            select(ProjectRate).where(ProjectRate.project_id == project_id)
        )
        proj_rates = {pr.work_type_id: pr.rate for pr in result.scalars().all()}

    lines = [t(lang, "rates.project_rates", project=project.name), ""]
    buttons = []
    for wt in work_types:
        ul = unit_label(wt.unit, lang)
        rate = proj_rates.get(wt.id, wt.default_rate)
        is_custom = wt.id in proj_rates
        marker = "🔸" if is_custom else "⚪"
        lines.append(f"{marker} {t(lang, 'rates.rate_line', work_type=wt.get_name(lang), rate=f'{rate:.2f}', currency=curr_sym, unit=ul)}")
        buttons.append([InlineKeyboardButton(
            f"✏️ {wt.get_name(lang)}",
            callback_data=f"rt:edit_proj:{wt.id}"
        )])

    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="rt:by_project")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def edit_project_rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    wt_id = int(query.data.split(":")[2])
    context.user_data["rt_wt_id"] = wt_id
    context.user_data["rt_mode"] = "project"

    async with async_session() as session:
        result = await session.execute(select(WorkType).where(WorkType.id == wt_id))
        wt = result.scalar_one()
        ul = unit_label(wt.unit, lang)

    await query.edit_message_text(
        t(lang, "rates.enter_rate", work_type=wt.get_name(lang), unit=ul)
    )
    return RT_EDIT_VALUE


async def rate_value_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip().replace(",", ".")

    try:
        rate = Decimal(text)
        if rate < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await update.message.reply_text("⚠️ Введіть число")
        return RT_EDIT_VALUE

    wt_id = context.user_data["rt_wt_id"]
    mode = context.user_data["rt_mode"]

    async with async_session() as session:
        if mode == "default":
            result = await session.execute(select(WorkType).where(WorkType.id == wt_id))
            wt = result.scalar_one()
            wt.default_rate = rate
        else:
            project_id = context.user_data["rt_project_id"]
            result = await session.execute(
                select(ProjectRate).where(
                    ProjectRate.project_id == project_id,
                    ProjectRate.work_type_id == wt_id,
                )
            )
            pr = result.scalar_one_or_none()
            if pr:
                pr.rate = rate
            else:
                pr = ProjectRate(
                    project_id=project_id,
                    work_type_id=wt_id,
                    rate=rate,
                )
                session.add(pr)
        await session.commit()

    await update.message.reply_text(t(lang, "rates.rate_updated"))
    await show_rates_menu(update, context)
    return ConversationHandler.END


def get_rates_handlers():
    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_default_rate_start, pattern=r"^rt:edit_def:\d+$"),
            CallbackQueryHandler(edit_project_rate_start, pattern=r"^rt:edit_proj:\d+$"),
        ],
        states={
            RT_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_value_entered)],
        },
        fallbacks=[],
        per_message=False,
    )

    return [
        edit_conv,
        CallbackQueryHandler(show_default_rates, pattern=r"^rt:defaults$"),
        CallbackQueryHandler(show_project_rates_selector, pattern=r"^rt:by_project$"),
        CallbackQueryHandler(show_project_rates, pattern=r"^rt:proj:\d+$"),
    ]
