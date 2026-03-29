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
from utils.rates import get_effective_rates_bulk

logger = logging.getLogger(__name__)


def _parse_date(text: str) -> date:
    """Parse date from DD.MM.YY or DD.MM.YYYY format."""
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {text}")


async def _get_worker_brigade_id(worker_id: int) -> int | None:
    """Get the brigade_id of a worker (first active membership)."""
    async with async_session() as session:
        result = await session.execute(
            select(BrigadeMember.brigade_id).where(
                BrigadeMember.worker_id == worker_id,
                BrigadeMember.is_active == True,
            ).limit(1)
        )
        row = result.first()
        return row[0] if row else None


async def _load_work_types_with_rates(info: dict, lang: str, project_id: int) -> list[dict]:
    """Load work types with effective rates considering brigade/project hierarchy."""
    async with async_session() as session:
        result = await session.execute(
            select(WorkType).where(
                WorkType.director_id == info["director_id"],
                WorkType.is_active == True,
            ).order_by(WorkType.sort_order)
        )
        work_types = result.scalars().all()

    # Determine brigade
    worker_id = info.get("worker_id")
    brigade_id = None
    if worker_id:
        brigade_id = await _get_worker_brigade_id(worker_id)

    wt_ids = [wt.id for wt in work_types]
    rates = await get_effective_rates_bulk(wt_ids, project_id, brigade_id)

    wt_list = []
    for wt in work_types:
        wt_list.append({
            "id": wt.id,
            "name": wt.get_name(lang),
            "unit": wt.unit,
            "rate": rates.get(wt.id, wt.default_rate),
        })
    return wt_list


async def _get_or_create_defaults(session, project_id):
    """Get or create a default (hidden) building and element for a project without buildings."""
    result = await session.execute(
        select(Building).where(
            Building.project_id == project_id,
            Building.name == "__default__",
        )
    )
    bld = result.scalar_one_or_none()
    if not bld:
        bld = Building(project_id=project_id, name="__default__", is_active=False)
        session.add(bld)
        await session.flush()

    result = await session.execute(
        select(Element).where(
            Element.building_id == bld.id,
            Element.name == "__default__",
        )
    )
    elem = result.scalar_one_or_none()
    if not elem:
        elem = Element(building_id=bld.id, name="__default__", element_type="other", is_active=False)
        session.add(elem)
        await session.commit()
    return bld, elem


async def _get_or_create_default_element(session, building_id, building_name):
    """Get or create a default (hidden) element for a building without elements."""
    result = await session.execute(
        select(Element).where(
            Element.building_id == building_id,
            Element.name == "__default__",
        )
    )
    elem = result.scalar_one_or_none()
    if not elem:
        result2 = await session.execute(select(Building).where(Building.id == building_id))
        bld = result2.scalar_one()
        elem = Element(building_id=building_id, name="__default__", element_type="other", is_active=False)
        session.add(elem)
        await session.commit()
    else:
        result2 = await session.execute(select(Building).where(Building.id == building_id))
        bld = result2.scalar_one()
    return bld, elem

# States
(WE_DATE, WE_DATE_INPUT, WE_PROJECT, WE_BUILDING, WE_ELEMENT,
 WE_SELECT_WT, WE_QUANTITY, WE_CONFIRM) = range(100, 108)


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
        d = _parse_date(text)
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
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_back_date")])

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
        # No buildings — write directly to project via auto-created default element
        default_bld, default_elem = await _get_or_create_defaults(session, project_id)
        context.user_data["we_building_id"] = default_bld.id
        context.user_data["we_building_name"] = proj.name
        context.user_data["we_element_id"] = default_elem.id
        context.user_data["we_element_name"] = proj.name

        wt_list = await _load_work_types_with_rates(info, lang, project_id)
        context.user_data["we_work_types"] = wt_list
        context.user_data["we_entries"] = {}

        return await _show_work_type_buttons(update, context)

    buttons = [[InlineKeyboardButton(b.name, callback_data=f"we_bld:{b.id}")]
               for b in buildings]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_back_projects")])

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
        # No elements — write directly to building via auto-created default element
        async with async_session() as session2:
            _, default_elem = await _get_or_create_default_element(session2, building_id, bld.name)
        context.user_data["we_element_id"] = default_elem.id
        context.user_data["we_element_name"] = bld.name

        project_id = context.user_data["we_project_id"]
        wt_list = await _load_work_types_with_rates(info, lang, project_id)
        context.user_data["we_work_types"] = wt_list
        context.user_data["we_entries"] = {}

        return await _show_work_type_buttons(update, context)

    buttons = [[InlineKeyboardButton(e.name, callback_data=f"we_elem:{e.id}")]
               for e in elements]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_back_buildings")])

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

        project_id = context.user_data["we_project_id"]
        wt_list = await _load_work_types_with_rates(info, lang, project_id)

    context.user_data["we_work_types"] = wt_list
    context.user_data["we_entries"] = {}
    # work types loaded

    return await _show_work_type_buttons(update, context)


async def _show_work_type_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show buttons for all work types. Worker picks which ones to fill."""
    info = context.user_data["info"]
    lang = info["lang"]
    wt_list = context.user_data["we_work_types"]
    entries = context.user_data["we_entries"]

    buttons = []
    for wt in wt_list:
        ul = unit_label(wt["unit"], lang)
        if wt["id"] in entries:
            # Already filled — show with checkmark and value
            qty = entries[wt["id"]]["quantity"]
            label = f"✅ {wt['name']} — {qty} {ul}"
        else:
            label = f"📝 {wt['name']} ({ul})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"we_wt:{wt['id']}")])

    buttons.append([InlineKeyboardButton(t(lang, "work.done"), callback_data="we_done")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="we_cancel")])

    text = t(lang, "work.select_work_types")

    msg = update.callback_query.message if update.callback_query else update.effective_message
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception:
            await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return WE_SELECT_WT


async def work_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Worker tapped a work type button — ask for quantity."""
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    wt_id = int(query.data.split(":")[1])
    context.user_data["we_active_wt_id"] = wt_id

    # Find the work type
    wt = None
    for w in context.user_data["we_work_types"]:
        if w["id"] == wt_id:
            wt = w
            break

    ul = unit_label(wt["unit"], lang)
    text = t(lang, "work.enter_quantity", work_type=wt["name"], unit=ul)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_back_wt")],
    ])

    await query.edit_message_text(text, reply_markup=keyboard)
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

    wt_id = context.user_data["we_active_wt_id"]

    # Find the work type
    wt = None
    for w in context.user_data["we_work_types"]:
        if w["id"] == wt_id:
            wt = w
            break

    if qty > 0:
        context.user_data["we_entries"][wt_id] = {
            "quantity": qty,
            "rate": wt["rate"],
            "name": wt["name"],
            "unit": wt["unit"],
        }
    elif wt_id in context.user_data["we_entries"]:
        # Entered 0 — remove previous entry
        del context.user_data["we_entries"][wt_id]

    return await _show_work_type_buttons(update, context)


async def back_to_work_types(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back from quantity input to work type selection."""
    await update.callback_query.answer()
    return await _show_work_type_buttons(update, context)


async def work_types_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Worker pressed Done — refresh rates from DB and show summary."""
    await update.callback_query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    entries = context.user_data["we_entries"]
    project_id = context.user_data["we_project_id"]

    if not entries:
        # Nothing entered
        return await _show_work_type_buttons(update, context)

    # Reload fresh rates before saving
    fresh_wt_list = await _load_work_types_with_rates(info, lang, project_id)
    fresh_rates = {wt["id"]: wt["rate"] for wt in fresh_wt_list}

    # Update entries with fresh rates
    for wt_id, entry in entries.items():
        if wt_id in fresh_rates:
            entry["rate"] = fresh_rates[wt_id]

    return await _show_summary(update, context)


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
    date_str = we_date.strftime("%d.%m.%y")

    # Build location string — skip default building/element
    bld_name = context.user_data.get("we_building_name", "")
    elem_name = context.user_data.get("we_element_name", "")
    proj_name = context.user_data["we_project_name"]

    if bld_name == proj_name and elem_name == proj_name:
        # Direct project entry — no building/element hierarchy
        location = f"📍 {proj_name}"
    elif elem_name == bld_name:
        # Direct building entry — no element
        location = f"📍 {proj_name} → {bld_name}"
    else:
        location = t(lang, "work.summary_location",
                      project=proj_name, building=bld_name, element=elem_name)

    lines = [
        t(lang, "work.summary_title", date=date_str),
        location,
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
                w = Worker(
                    telegram_id=update.effective_user.id,
                    director_id=info["director_id"],
                    name=info["name"],
                    language=lang,
                )
                session.add(w)
                await session.commit()
            worker_id = w.id

    async with async_session() as session:
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


async def back_to_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back from project list to date selection."""
    query = update.callback_query
    await query.answer()
    return await start_work_entry(update, context)


async def back_to_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back from building list to project list."""
    query = update.callback_query
    await query.answer()
    return await _show_projects(update, context)


async def back_to_buildings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back from element list to building list."""
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    project_id = context.user_data["we_project_id"]

    async with async_session() as session:
        result = await session.execute(
            select(Building).where(
                Building.project_id == project_id,
                Building.is_active == True,
            ).order_by(Building.name)
        )
        buildings = result.scalars().all()

    buttons = [[InlineKeyboardButton(b.name, callback_data=f"we_bld:{b.id}")]
               for b in buildings]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="we_back_projects")])

    await query.edit_message_text(
        t(lang, "work.select_building"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WE_BUILDING


def get_work_entry_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_work_entry, pattern=r"^menu:work$")],
        states={
            WE_DATE: [CallbackQueryHandler(date_selected, pattern=r"^we_date:")],
            WE_DATE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_entered)],
            WE_PROJECT: [
                CallbackQueryHandler(back_to_date, pattern=r"^we_back_date$"),
                CallbackQueryHandler(project_selected, pattern=r"^we_proj:"),
            ],
            WE_BUILDING: [
                CallbackQueryHandler(back_to_projects, pattern=r"^we_back_projects$"),
                CallbackQueryHandler(building_selected, pattern=r"^we_bld:"),
            ],
            WE_ELEMENT: [
                CallbackQueryHandler(back_to_buildings, pattern=r"^we_back_buildings$"),
                CallbackQueryHandler(element_selected, pattern=r"^we_elem:"),
            ],
            WE_SELECT_WT: [
                CallbackQueryHandler(work_type_selected, pattern=r"^we_wt:\d+$"),
                CallbackQueryHandler(work_types_done, pattern=r"^we_done$"),
            ],
            WE_QUANTITY: [
                CallbackQueryHandler(back_to_work_types, pattern=r"^we_back_wt$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_entered),
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
