import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select

from database import async_session
from models import Project, Building, Element, Client
from utils.i18n import t
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

PJ_CREATE_NAME, PJ_CREATE_ADDR = 300, 301
PJ_ADD_BLD_NAME = 302
PJ_ADD_ELEM_NAME, PJ_ADD_ELEM_TYPE = 303, 304
PJ_RENAME = 305
PJ_RENAME_BLD = 306
PJ_RENAME_ELEM = 307
PJ_CLIENT = 308

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
        if role == "director":
            buttons.append([InlineKeyboardButton(t(lang, "projects.archive_list"), callback_data="pj:archive_list")])
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
    if project.client_id:
        async with async_session() as session2:
            result = await session2.execute(select(Client).where(Client.id == project.client_id))
            client = result.scalar_one_or_none()
            if client:
                lines.append(f"👤 {client.name}")
    if project.address:
        lines.append(f"📍 {project.address}")
    if project.created_at:
        lines.append(f"📅 {project.created_at.strftime('%d.%m.%y')}")
    lines.append("")

    buttons = []
    for b in buildings:
        buttons.append([InlineKeyboardButton(f"🏠 {b.name}", callback_data=f"pj:bld:{b.id}")])

    if info["role"] in ("director", "brigadier"):
        buttons.append([InlineKeyboardButton(t(lang, "projects.add_building"), callback_data=f"pj:add_bld:{project_id}")])
        if info["role"] == "director":
            buttons.append([InlineKeyboardButton(t(lang, "projects.rename"), callback_data=f"pj:rename:{project_id}")])
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
        buttons.append([InlineKeyboardButton(f"{etype} {e.name}", callback_data=f"pj:view_elem:{e.id}")])

    if info["role"] in ("director", "brigadier"):
        buttons.append([InlineKeyboardButton(t(lang, "projects.add_element"),
                                              callback_data=f"pj:add_elem:{building_id}")])
        if info["role"] == "director":
            buttons.append([InlineKeyboardButton(t(lang, "projects.rename_building"),
                                                  callback_data=f"pj:rename_bld:{building_id}")])
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
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    context.user_data["info"] = info
    lang = info["lang"]

    # Show client selection
    async with async_session() as session:
        result = await session.execute(
            select(Client).where(
                Client.director_id == info["director_id"],
                Client.is_active == True,
            ).order_by(Client.name)
        )
        clients = result.scalars().all()

    buttons = []
    for c in clients:
        buttons.append([InlineKeyboardButton(f"👤 {c.name}", callback_data=f"pj:client:{c.id}")])
    buttons.append([InlineKeyboardButton(t(lang, "projects.new_client"), callback_data="pj:new_client")])
    buttons.append([InlineKeyboardButton(t(lang, "projects.no_client"), callback_data="pj:no_client")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="menu:projects")])

    await query.edit_message_text(
        t(lang, "projects.select_client"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return PJ_CLIENT


async def client_selected_for_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    client_id = int(query.data.split(":")[2])
    context.user_data["pj_client_id"] = client_id

    async with async_session() as session:
        result = await session.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one()
        context.user_data["pj_client_name"] = client.name

    await query.edit_message_text(
        t(lang, "projects.enter_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="menu:projects")]
        ])
    )
    return PJ_CREATE_NAME


async def no_client_for_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    context.user_data["pj_client_id"] = None

    await query.edit_message_text(
        t(lang, "projects.enter_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="menu:projects")]
        ])
    )
    return PJ_CREATE_NAME


async def new_client_for_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    context.user_data["cl_from_project"] = True

    await query.edit_message_text(
        t(lang, "clients.enter_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="pj:back_client")]
        ])
    )
    return PJ_CREATE_NAME


async def _continue_project_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Called after inline client creation to continue with project name."""
    info = context.user_data["info"]
    lang = info["lang"]
    msg = update.effective_message or update.callback_query.message
    await msg.reply_text(
        t(lang, "projects.enter_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="menu:projects")]
        ])
    )
    return PJ_CREATE_NAME


async def back_to_client_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back from new client name to client selection."""
    await update.callback_query.answer()
    context.user_data["cl_from_project"] = False
    return await create_project_start(update, context)


async def create_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip()

    # Check if we're creating an inline client
    if context.user_data.get("cl_from_project"):
        context.user_data["cl_from_project"] = False
        async with async_session() as session:
            client = Client(director_id=info["director_id"], name=text)
            session.add(client)
            await session.commit()
            await session.refresh(client)
            context.user_data["pj_client_id"] = client.id
            context.user_data["pj_client_name"] = text

        await update.message.reply_text(t(lang, "clients.created", name=text))
        await update.message.reply_text(
            t(lang, "projects.enter_name"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="menu:projects")]
            ])
        )
        return PJ_CREATE_NAME

    # Normal project name
    context.user_data["pj_name"] = text

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

    project_name = context.user_data["pj_name"]
    client_name = context.user_data.get("pj_client_name")
    if client_name:
        project_name = f"{project_name} — {client_name}"

    async with async_session() as session:
        project = Project(
            director_id=info["director_id"],
            client_id=context.user_data.get("pj_client_id"),
            name=project_name,
            address=address,
        )
        session.add(project)
        await session.commit()

    await (update.message or update.callback_query.message).reply_text(
        t(lang, "projects.created", name=project_name)
    )
    await show_projects_menu(update, context)
    return ConversationHandler.END


async def create_project_addr_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    info = context.user_data["info"]
    lang = info["lang"]

    project_name = context.user_data["pj_name"]
    client_name = context.user_data.get("pj_client_name")
    if client_name:
        project_name = f"{project_name} — {client_name}"

    async with async_session() as session:
        project = Project(
            director_id=info["director_id"],
            client_id=context.user_data.get("pj_client_id"),
            name=project_name,
        )
        session.add(project)
        await session.commit()

    await update.callback_query.edit_message_text(
        t(lang, "projects.created", name=project_name)
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
    await query.edit_message_text(
        t(lang, "projects.enter_building_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"pj:view:{project_id}")]
        ])
    )
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
    await query.edit_message_text(
        t(lang, "projects.enter_element_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"pj:bld:{building_id}")]
        ])
    )
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


# --- View element (with rename option) ---
async def view_element(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    element_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Element).where(Element.id == element_id))
        element = result.scalar_one()

    etype = t(lang, f"projects.element_types.{element.element_type}") if element.element_type else ""
    text = f"{etype} {element.name}"

    buttons = []
    if info["role"] == "director":
        buttons.append([InlineKeyboardButton(t(lang, "projects.rename_element"),
                                              callback_data=f"pj:rename_elem:{element_id}")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"),
                                          callback_data=f"pj:bld:{element.building_id}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# --- Rename project ---
async def rename_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])
    context.user_data["rename_project_id"] = project_id
    await query.edit_message_text(
        t(lang, "projects.enter_new_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"pj:view:{project_id}")]
        ])
    )
    return PJ_RENAME


async def rename_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    new_name = update.message.text.strip()
    project_id = context.user_data["rename_project_id"]

    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()
        project.name = new_name
        await session.commit()

    await update.message.reply_text(t(lang, "projects.renamed", name=new_name))
    await show_projects_menu(update, context)
    return ConversationHandler.END


# --- Rename building ---
async def rename_building_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    building_id = int(query.data.split(":")[2])
    context.user_data["rename_building_id"] = building_id
    await query.edit_message_text(
        t(lang, "projects.enter_new_building_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"pj:bld:{building_id}")]
        ])
    )
    return PJ_RENAME_BLD


async def rename_building_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    new_name = update.message.text.strip()
    building_id = context.user_data["rename_building_id"]

    async with async_session() as session:
        result = await session.execute(select(Building).where(Building.id == building_id))
        building = result.scalar_one()
        building.name = new_name
        await session.commit()

    await update.message.reply_text(t(lang, "projects.building_renamed", name=new_name))
    await show_projects_menu(update, context)
    return ConversationHandler.END


# --- Rename element ---
async def rename_element_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    element_id = int(query.data.split(":")[2])
    context.user_data["rename_element_id"] = element_id
    await query.edit_message_text(
        t(lang, "projects.enter_new_element_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"pj:view_elem:{element_id}")]
        ])
    )
    return PJ_RENAME_ELEM


async def rename_element_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    new_name = update.message.text.strip()
    element_id = context.user_data["rename_element_id"]

    async with async_session() as session:
        result = await session.execute(select(Element).where(Element.id == element_id))
        element = result.scalar_one()
        element.name = new_name
        await session.commit()

    await update.message.reply_text(t(lang, "projects.element_renamed", name=new_name))
    await show_projects_menu(update, context)
    return ConversationHandler.END


async def rename_project_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await view_project(update, context)
    return ConversationHandler.END


async def rename_building_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await view_building(update, context)
    return ConversationHandler.END


async def rename_element_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await view_element(update, context)
    return ConversationHandler.END


async def create_project_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_projects_menu(update, context)
    return ConversationHandler.END


async def add_building_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await view_project(update, context)
    return ConversationHandler.END


async def add_element_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await view_building(update, context)
    return ConversationHandler.END


# --- Archive ---
async def archive_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()
        project.is_archived = True
        from datetime import datetime
        project.archived_at = datetime.utcnow()
        await session.commit()
        name = project.name

    await query.edit_message_text(t(lang, "projects.archived", name=name))
    await show_projects_menu(update, context)


async def show_archive_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]

    async with async_session() as session:
        result = await session.execute(
            select(Project).where(
                Project.director_id == info["director_id"],
                Project.is_archived == True,
            ).order_by(Project.archived_at.desc().nullslast(), Project.name)
        )
        projects = result.scalars().all()

    if not projects:
        text = t(lang, "projects.no_archived")
        buttons = [[InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:projects")]]
    else:
        text = t(lang, "projects.archive_title")
        buttons = []
        for p in projects:
            date_str = ""
            if p.created_at:
                date_str += p.created_at.strftime("%d.%m.%y")
            if p.archived_at:
                date_str += f" → {p.archived_at.strftime('%d.%m.%y')}"
            label = f"📦 {p.name}"
            if date_str:
                label += f" ({date_str})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"pj:view_archived:{p.id}")])
        buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:projects")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def view_archived_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()

        result = await session.execute(
            select(Building).where(
                Building.project_id == project_id,
            ).order_by(Building.name)
        )
        buildings = result.scalars().all()

    lines = [f"📦 {project.name}"]
    if project.address:
        lines.append(f"📍 {project.address}")
    if project.created_at:
        lines.append(f"📅 {t(lang, 'projects.date_created')}: {project.created_at.strftime('%d.%m.%y')}")
    if project.archived_at:
        lines.append(f"📦 {t(lang, 'projects.date_archived')}: {project.archived_at.strftime('%d.%m.%y')}")
    lines.append("")

    if buildings:
        for b in buildings:
            lines.append(f"🏠 {b.name}")
    else:
        lines.append("—")

    buttons = []
    if info["role"] == "director":
        buttons.append([InlineKeyboardButton(t(lang, "projects.unarchive"), callback_data=f"pj:unarchive:{project_id}")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="pj:archive_list")])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def unarchive_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    project_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()
        project.is_archived = False
        project.archived_at = None
        await session.commit()
        name = project.name

    await query.edit_message_text(t(lang, "projects.unarchived", name=name))
    await show_projects_menu(update, context)


def get_projects_handlers():
    create_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_project_start, pattern=r"^pj:create$")],
        states={
            PJ_CLIENT: [
                CallbackQueryHandler(create_project_cancel, pattern=r"^menu:projects$"),
                CallbackQueryHandler(client_selected_for_project, pattern=r"^pj:client:\d+$"),
                CallbackQueryHandler(no_client_for_project, pattern=r"^pj:no_client$"),
                CallbackQueryHandler(new_client_for_project_start, pattern=r"^pj:new_client$"),
            ],
            PJ_CREATE_NAME: [
                CallbackQueryHandler(create_project_cancel, pattern=r"^menu:projects$"),
                CallbackQueryHandler(back_to_client_selection, pattern=r"^pj:back_client$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_name),
            ],
            PJ_CREATE_ADDR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_project_addr),
                CallbackQueryHandler(create_project_addr_skip, pattern=r"^skip$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(create_project_cancel, pattern=r"^menu:projects$")],
        per_message=False,
    )

    add_bld_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_building_start, pattern=r"^pj:add_bld:\d+$")],
        states={
            PJ_ADD_BLD_NAME: [
                CallbackQueryHandler(add_building_cancel, pattern=r"^pj:view:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_building_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(add_building_cancel, pattern=r"^pj:view:\d+$")],
        per_message=False,
    )

    add_elem_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_element_start, pattern=r"^pj:add_elem:\d+$")],
        states={
            PJ_ADD_ELEM_NAME: [
                CallbackQueryHandler(add_element_cancel, pattern=r"^pj:bld:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_element_name),
            ],
            PJ_ADD_ELEM_TYPE: [CallbackQueryHandler(add_element_type, pattern=r"^pj:etype:")],
        },
        fallbacks=[CallbackQueryHandler(add_element_cancel, pattern=r"^pj:bld:\d+$")],
        per_message=False,
    )

    rename_proj_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rename_project_start, pattern=r"^pj:rename:\d+$")],
        states={
            PJ_RENAME: [
                CallbackQueryHandler(rename_project_cancel, pattern=r"^pj:view:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_project_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(rename_project_cancel, pattern=r"^pj:view:\d+$")],
        per_message=False,
    )

    rename_bld_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rename_building_start, pattern=r"^pj:rename_bld:\d+$")],
        states={
            PJ_RENAME_BLD: [
                CallbackQueryHandler(rename_building_cancel, pattern=r"^pj:bld:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_building_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(rename_building_cancel, pattern=r"^pj:bld:\d+$")],
        per_message=False,
    )

    rename_elem_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rename_element_start, pattern=r"^pj:rename_elem:\d+$")],
        states={
            PJ_RENAME_ELEM: [
                CallbackQueryHandler(rename_element_cancel, pattern=r"^pj:view_elem:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_element_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(rename_element_cancel, pattern=r"^pj:view_elem:\d+$")],
        per_message=False,
    )

    return [
        create_conv,
        add_bld_conv,
        add_elem_conv,
        rename_proj_conv,
        rename_bld_conv,
        rename_elem_conv,
        CallbackQueryHandler(view_project, pattern=r"^pj:view:\d+$"),
        CallbackQueryHandler(view_building, pattern=r"^pj:bld:\d+$"),
        CallbackQueryHandler(view_element, pattern=r"^pj:view_elem:\d+$"),
        CallbackQueryHandler(archive_project, pattern=r"^pj:archive:\d+$"),
        CallbackQueryHandler(show_archive_list, pattern=r"^pj:archive_list$"),
        CallbackQueryHandler(view_archived_project, pattern=r"^pj:view_archived:\d+$"),
        CallbackQueryHandler(unarchive_project, pattern=r"^pj:unarchive:\d+$"),
    ]
