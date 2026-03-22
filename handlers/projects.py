import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select

from database import async_session
from models import Project, Building, Element
from utils.i18n import t
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

PJ_CREATE_NAME, PJ_CREATE_ADDR = 300, 301
PJ_ADD_BLD_NAME = 302
PJ_ADD_ELEM_NAME, PJ_ADD_ELEM_TYPE = 303, 304

ELEMENT_TYPES = ["wall", "parter", "terrace", "balcony", "ceiling", "other"]


async def show_projects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]
    role = info["role"]

    async with async_session() as session:
        result = await session.execute(
            select(Project).where(
                Project.director_id == info["director_id"],
                Project.is_active == True,
                Project.is_archived == False,
            ).order_by(Project.name)
        )
        projects = result.scalars().all()

    if not projects:
        buttons = []
        if role in ("director", "brigadier"):
            buttons.append([InlineKeyboardButton(t(lang, "projects.create"), callback_data="pj:create")])
        buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])
        text = t(lang, "projects.no_projects")
    else:
        buttons = [[InlineKeyboardButton(f"🏗️ {p.name}", callback_data=f"pj:view:{p.id}")]
                    for p in projects]
        if role in ("director", "brigadier"):
            buttons.append([InlineKeyboardButton(t(lang, "projects.create"), callback_data="pj:create")])
        buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])
        text = t(lang, "projects.title")

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def view_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])
    context.user_data["current_project_id"] = project_id

    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()

        result = await session.execute(
            select(Building).where(
                Building.project_id == project_id,
                Building.is_active == True,
            ).order_by(Building.name)
        )
        buildings = result.scalars().all()

    lines = [f"🏗️ {project.name}"]
    if project.address:
        lines.append(f"📍 {project.address}")
    lines.append("")

    buttons = []
    for b in buildings:
        buttons.append([InlineKeyboardButton(f"🏠 {b.name}", callback_data=f"pj:bld:{b.id}")])

    if info["role"] in ("director", "brigadier"):
        buttons.append([InlineKeyboardButton(t(lang, "projects.add_building"), callback_data=f"pj:add_bld:{project_id}")])
        if info["role"] == "director":
            buttons.append([InlineKeyboardButton(t(lang, "btn.archive"), callback_data=f"pj:archive:{project_id}")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:projects")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def view_building(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    building_id = int(query.data.split(":")[2])
    context.user_data["current_building_id"] = building_id

    async with async_session() as session:
        result = await session.execute(select(Building).where(Building.id == building_id))
        building = result.scalar_one()

        result = await session.execute(
            select(Element).where(
                Element.building_id == building_id,
                Element.is_active == True,
            ).order_by(Element.name)
        )
        elements = result.scalars().all()

    lines = [f"🏠 {building.name}", ""]
    buttons = []
    for e in elements:
        etype = t(lang, f"projects.element_types.{e.element_type}") if e.element_type else ""
        buttons.append([InlineKeyboardButton(f"{etype} {e.name}", callback_data=f"pj:elem_noop:{e.id}")])

    if info["role"] in ("director", "brigadier"):
        buttons.append([InlineKeyboardButton(t(lang, "projects.add_element"),
                                              callback_data=f"pj:add_elem:{building_id}")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"),
                                          callback_data=f"pj:view:{building.project_id}")])

    await query.edit_message_text(
        "\n".join(lines) + ("\n".join(f"• {e.name}" for e in elements) if elements else "—"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# --- Create project ---
async def create_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    await query.edit_message_text(t(lang, "projects.enter_name"))
    return PJ_CREATE_NAME


async def create_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    context.user_data["pj_name"] = update.message.text.strip()

    from utils.keyboards import skip_keyboard
    await update.message.reply_text(
        t(lang, "projects.enter_address"),
        reply_markup=skip_keyboard(lang)
    )
    return PJ_CREATE_ADDR


async def create_project_addr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    address = update.message.text.strip() if update.message else None

    async with async_session() as session:
        project = Project(
            director_id=info["director_id"],
            name=context.user_data["pj_name"],
            address=address,
        )
        session.add(project)
        await session.commit()

    await (update.message or update.callback_query.message).reply_text(
        t(lang, "projects.created", name=context.user_data["pj_name"])
    )
    await show_projects_menu(update, context)
    return ConversationHandler.END


async def create_project_addr_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    info = context.user_data["info"]
    lang = info["lang"]

    async with async_session() as session:
        project = Project(
            director_id=info["director_id"],
            name=context.user_data["pj_name"],
        )
        session.add(project)
        await session.commit()

    await update.callback_query.edit_message_text(
        t(lang, "projects.created", name=context.user_data["pj_name"])
    )
    await show_projects_menu(update, context)
    return ConversationHandler.END


# --- Add building ---
async def add_building_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])
    context.user_data["add_bld_project_id"] = project_id
    await query.edit_message_text(t(lang, "projects.enter_building_name"))
    return PJ_ADD_BLD_NAME


async def add_building_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    name = update.message.text.strip()

    async with async_session() as session:
        building = Building(
            project_id=context.user_data["add_bld_project_id"],
            name=name,
        )
        session.add(building)
        await session.commit()

    await update.message.reply_text(t(lang, "projects.building_created", name=name))
    await show_projects_menu(update, context)
    return ConversationHandler.END


# --- Add element ---
async def add_element_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    building_id = int(query.data.split(":")[2])
    context.user_data["add_elem_building_id"] = building_id
    await query.edit_message_text(t(lang, "projects.enter_element_name"))
    return PJ_ADD_ELEM_NAME


async def add_element_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    context.user_data["add_elem_name"] = update.message.text.strip()

    buttons = [[InlineKeyboardButton(t(lang, f"projects.element_types.{et}"),
                                      callback_data=f"pj:etype:{et}")]
               for et in ELEMENT_TYPES]

    await update.message.reply_text(
        t(lang, "projects.select_element_type"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return PJ_ADD_ELEM_TYPE


async def add_element_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    etype = query.data.split(":")[2]

    async with async_session() as session:
        element = Element(
            building_id=context.user_data["add_elem_building_id"],
            name=context.user_data["add_elem_name"],
            element_type=etype,
        )
        session.add(element)
        await session.commit()

    await query.edit_message_text(
        t(lang, "projects.element_created", name=context.user_data["add_elem_name"])
    )
    await show_projects_menu(update, context)
    return ConversationHandler.END


# --- Archive ---
async def archive_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info")
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()
        project.is_archived = True
        await session.commit()
        name = project.name

    await query.edit_message_text(t(lang, "projects.archived", name=name))
    await show_projects_menu(update, context)


def get_projects_handlers():
    create_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_project_start, pattern=r"^pj:create$")],
        states={
            PJ_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_name)],
            PJ_CREATE_ADDR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_addr),
                CallbackQueryHandler(create_project_addr_skip, pattern=r"^skip$"),
            ],
        },
        fallbacks=[],
        per_message=False,
    )

    add_bld_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_building_start, pattern=r"^pj:add_bld:\d+$")],
        states={
            PJ_ADD_BLD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_building_name)],
        },
        fallbacks=[],
        per_message=False,
    )

    add_elem_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_element_start, pattern=r"^pj:add_elem:\d+$")],
        states={
            PJ_ADD_ELEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_element_name)],
            PJ_ADD_ELEM_TYPE: [CallbackQueryHandler(add_element_type, pattern=r"^pj:etype:")],
        },
        fallbacks=[],
        per_message=False,
    )

    return [
        create_conv,
        add_bld_conv,
        add_elem_conv,
        CallbackQueryHandler(view_project, pattern=r"^pj:view:\d+$"),
        CallbackQueryHandler(view_building, pattern=r"^pj:bld:\d+$"),
        CallbackQueryHandler(archive_project, pattern=r"^pj:archive:\d+$"),
        CallbackQueryHandler(lambda u, c: None, pattern=r"^pj:elem_noop:\d+$"),
    ]
