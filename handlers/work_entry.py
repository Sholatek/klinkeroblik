import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import async_session
from models import (
    Project, Building, Element, WorkType, ProjectRate,
    WorkEntry, WorkEntryItem, Worker, Director, BrigadeMember,
)
from utils.i18n import t, unit_label, currency_symbol
from utils.keyboards import back_button
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

# States
(WE_DATE, WE_DATE_INPUT, WE_PROJECT, WE_BUILDING, WE_ELEMENT,
 WE_QUANTITY, WE_CONFIRM) = range(100, 107)


async def start_work_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Called from menu — start work entry flow."""
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return ConversationHandler.END
    context.user_data["info"] = info
    lang = info["lang"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "work.today"), callback_data="we_date:today")],
        [InlineKeyboardButton(t(lang, "work.other_date"), callback_data="we_date:other")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_cancel")],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            t(lang, "work.select_date"), reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            t(lang, "work.select_date"), reply_markup=keyboard
        )
    return WE_DATE


async def date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    choice = query.data.split(":")[1]

    if choice == "today":
        context.user_data["we_date"] = date.today()
        return await _show_projects(update, context)
    else:
        await query.edit_message_text(t(lang, "work.enter_date"))
        return WE_DATE_INPUT


async def date_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip()

    try:
        d = datetime.strptime(text, "%d.%m.%Y").date()
        context.user_data["we_date"] = d
        return await _show_projects(update, context)
    except ValueError:
        await update.message.reply_text(t(lang, "work.invalid_date"))
        return WE_DATE_INPUT


async def _show_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    director_id = info["director_id"]

    async with async_session() as session:
        result = await session.execute(
            select(Project).where(
                Project.director_id == director_id,
                Project.is_active == True,
                Project.is_archived == False,
            ).order_by(Project.name)
        )
        projects = result.scalars().all()

    if not projects:
        msg = update.effective_message or update.callback_query.message
        await msg.reply_text(t(lang, "work.no_projects"),
                             reply_markup=back_button(lang, "we_cancel"))
        return WE_PROJECT

    buttons = [[InlineKeyboardButton(p.name, callback_data=f"we_proj:{p.id}")]
               for p in projects]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_cancel")])

    msg = update.effective_message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            t(lang, "work.select_project"),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await msg.reply_text(
            t(lang, "work.select_project"),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    return WE_PROJECT


async def project_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    project_id = int(query.data.split(":")[1])
    context.user_data["we_project_id"] = project_id

    async with async_session() as session:
        result = await session.execute(
            select(Building).where(
                Building.project_id == project_id,
                Building.is_active == True,
            ).order_by(Building.name)
        )
        buildings = result.scalars().all()

        # Save project name
        result2 = await session.execute(select(Project).where(Project.id == project_id))
        proj = result2.scalar_one()
        context.user_data["we_project_name"] = proj.name

    if not buildings:
        await query.edit_message_text(
            t(lang, "work.no_buildings"),
            reply_markup=back_button(lang, "we_cancel")
        )
        return WE_BUILDING

    buttons = [[InlineKeyboardButton(b.name, callback_data=f"we_bld:{b.id}")]
               for b in buildings]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_cancel")])

    await query.edit_message_text(
        t(lang, "work.select_building"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WE_BUILDING


async def building_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    building_id = int(query.data.split(":")[1])
    context.user_data["we_building_id"] = building_id

    async with async_session() as session:
        result = await session.execute(
            select(Element).where(
                Element.building_id == building_id,
                Element.is_active == True,
            ).order_by(Element.name)
        )
        elements = result.scalars().all()

        result2 = await session.execute(select(Building).where(Building.id == building_id))
        bld = result2.scalar_one()
        context.user_data["we_building_name"] = bld.name

    if not elements:
        await query.edit_message_text(
            t(lang, "work.no_elements"),
            reply_markup=back_button(lang, "we_cancel")
        )
        return WE_ELEMENT

    buttons = [[InlineKeyboardButton(e.name, callback_data=f"we_elem:{e.id}")]
               for e in elements]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_cancel")])

    await query.edit_message_text(
        t(lang, "work.select_element"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WE_ELEMENT


async def element_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    element_id = int(query.data.split(":")[1])
    context.user_data["we_element_id"] = element_id

    async with async_session() as session:
        result = await session.execute(select(Element).where(Element.id == element_id))
        elem = result.scalar_one()
        context.user_data["we_element_name"] = elem.name

        # Load work types
        result = await session.execute(
            select(WorkType).where(
                WorkType.director_id == info["director_id"],
                WorkType.is_active == True,
            ).order_by(WorkType.sort_order)
        )
        work_types = result.scalars().all()

        # Load project-specific rates
        project_id = context.user_data["we_project_id"]
        result = await session.execute(
            select(ProjectRate).where(ProjectRate.project_id == project_id)
        )
        project_rates = {pr.work_type_id: pr.rate for pr in result.scalars().all()}

    # Prepare work types with effective rates
    wt_list = []
    for wt in work_types:
        effective_rate = project_rates.get(wt.id, wt.default_rate)
        wt_list.append({
            "id": wt.id,
            "name": wt.get_name(lang),
            "unit": wt.unit,
            "rate": effective_rate,
        })

    context.user_data["we_work_types"] = wt_list
    context.user_data["we_entries"] = {}
    context.user_data["we_current_wt"] = 0

    return await _ask_next_quantity(update, context)


async def _ask_next_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    wt_list = context.user_data["we_work_types"]
    idx = context.user_data["we_current_wt"]

    if idx >= len(wt_list):
        return await _show_summary(update, context)

    wt = wt_list[idx]
    unit = unit_label(wt["unit"], lang)
    text = t(lang, "work.enter_quantity", work_type=wt["name"], unit=unit)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.skip"), callback_data="we_skip")],
        [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="we_cancel")],
    ])

    msg = update.callback_query.message if update.callback_query else update.effective_message
    await msg.reply_text(text, reply_markup=keyboard)
    return WE_QUANTITY


async def quantity_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip().replace(",", ".")

    try:
        qty = Decimal(text)
        if qty < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await update.message.reply_text("⚠️ Введіть число (наприклад: 12.5)")
        return WE_QUANTITY

    wt_list = context.user_data["we_work_types"]
    idx = context.user_data["we_current_wt"]
    wt = wt_list[idx]

    if qty > 0:
        context.user_data["we_entries"][wt["id"]] = {
            "quantity": qty,
            "rate": wt["rate"],
            "name": wt["name"],
            "unit": wt["unit"],
        }

    context.user_data["we_current_wt"] = idx + 1
    return await _ask_next_quantity(update, context)


async def quantity_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["we_current_wt"] += 1
    return await _ask_next_quantity(update, context)


async def _show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    entries = context.user_data["we_entries"]

    # Get currency
    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        curr = director.currency

    curr_sym = currency_symbol(curr)

    if not entries:
        msg = update.callback_query.message if update.callback_query else update.effective_message
        await msg.reply_text(t(lang, "work.nothing_entered"))
        from handlers.menu import show_main_menu
        await show_main_menu(update, context, send_new=True)
        return ConversationHandler.END

    we_date = context.user_data["we_date"]
    date_str = we_date.strftime("%d.%m.%Y")

    lines = [
        t(lang, "work.summary_title", date=date_str),
        t(lang, "work.summary_location",
          project=context.user_data["we_project_name"],
          building=context.user_data["we_building_name"],
          element=context.user_data["we_element_name"]),
        "",
    ]

    grand_total = Decimal("0")
    for wt_id, entry in entries.items():
        total = entry["quantity"] * entry["rate"]
        grand_total += total
        ul = unit_label(entry["unit"], lang)
        lines.append(t(lang, "work.summary_line",
                       work_type=entry["name"],
                       quantity=f"{entry['quantity']:.2f}",
                       unit=ul,
                       rate=f"{entry['rate']:.2f}",
                       currency=curr_sym,
                       total=f"{total:.2f}"))

    lines.append("")
    lines.append(t(lang, "work.summary_total",
                   total=f"{grand_total:.2f}", currency=curr_sym))

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(lang, "btn.confirm"), callback_data="we_save"),
            InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="we_cancel"),
        ]
    ])

    msg = update.callback_query.message if update.callback_query else update.effective_message
    await msg.reply_text("\n".join(lines), reply_markup=keyboard)
    return WE_CONFIRM


async def save_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    entries = context.user_data["we_entries"]

    # Determine worker_id
    worker_id = info.get("worker_id")
    if info["role"] == "director" and not worker_id:
        # Director acting as worker — find or create worker record
        async with async_session() as session:
            result = await session.execute(
                select(Worker).where(Worker.telegram_id == update.effective_user.id)
            )
            w = result.scalar_one_or_none()
            if not w:
                # Director doesn't have a worker record — create one
                from models import Worker as WorkerModel
                w = WorkerModel(
                    telegram_id=update.effective_user.id,
                    director_id=info["director_id"],
                    name=info["name"],
                    language=lang,
                )
                session.add(w)
                await session.flush()
            worker_id = w.id
            # Don't commit yet, we'll use a new session below

    async with async_session() as session:
        # If we just created a worker above, re-fetch
        if info["role"] == "director" and not info.get("worker_id"):
            result = await session.execute(
                select(Worker).where(Worker.telegram_id == update.effective_user.id)
            )
            w = result.scalar_one_or_none()
            if w:
                worker_id = w.id

        entry = WorkEntry(
            worker_id=worker_id,
            element_id=context.user_data["we_element_id"],
            work_date=context.user_data["we_date"],
            is_confirmed=True,
        )
        session.add(entry)
        await session.flush()

        for wt_id, data in entries.items():
            total = data["quantity"] * data["rate"]
            item = WorkEntryItem(
                entry_id=entry.id,
                work_type_id=wt_id,
                quantity=data["quantity"],
                rate_applied=data["rate"],
                total=total,
            )
            session.add(item)

        await session.commit()

    await query.edit_message_text(t(lang, "work.confirmed"))
    from handlers.menu import show_main_menu
    await show_main_menu(update, context, send_new=True)
    return ConversationHandler.END


async def cancel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info", {})
    lang = info.get("lang", "uk")
    await query.edit_message_text(t(lang, "work.cancelled"))
    from handlers.menu import show_main_menu
    await show_main_menu(update, context, send_new=True)
    return ConversationHandler.END


def get_work_entry_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_work_entry, pattern=r"^menu:work$")],
        states={
            WE_DATE: [CallbackQueryHandler(date_selected, pattern=r"^we_date:")],
            WE_DATE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_entered)],
            WE_PROJECT: [CallbackQueryHandler(project_selected, pattern=r"^we_proj:")],
            WE_BUILDING: [CallbackQueryHandler(building_selected, pattern=r"^we_bld:")],
            WE_ELEMENT: [CallbackQueryHandler(element_selected, pattern=r"^we_elem:")],
            WE_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_entered),
                CallbackQueryHandler(quantity_skipped, pattern=r"^we_skip$"),
            ],
            WE_CONFIRM: [
                CallbackQueryHandler(save_entry, pattern=r"^we_save$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_entry, pattern=r"^we_cancel$"),
        ],
        per_message=False,
        allow_reentry=True,
    )
