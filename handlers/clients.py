import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select
from database import async_session
from models import Client
from utils.i18n import t
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)

CL_CREATE_NAME, CL_CREATE_PHONE, CL_CREATE_NOTES = 800, 801, 802
CL_RENAME = 803


async def show_clients_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]

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
        label = f"👤 {c.name}"
        if c.phone:
            label += f" ({c.phone})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"cl:view:{c.id}")])

    buttons.append([InlineKeyboardButton(t(lang, "clients.add"), callback_data="cl:create")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])

    text = t(lang, "clients.title")

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(buttons)
        )


async def view_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]
    client_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one()

    lines = [f"👤 {client.name}"]
    if client.phone:
        lines.append(f"📞 {client.phone}")
    if client.email:
        lines.append(f"📧 {client.email}")
    if client.notes:
        lines.append(f"📝 {client.notes}")

    buttons = [
        [InlineKeyboardButton(t(lang, "clients.rename"), callback_data=f"cl:rename:{client_id}")],
        [InlineKeyboardButton(t(lang, "clients.delete"), callback_data=f"cl:delete:{client_id}")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:clients")],
    ]

    await query.edit_message_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons)
    )


# ─── Create client ───

async def create_client_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    context.user_data["info"] = info
    lang = info["lang"]
    # Track if we're creating from project flow
    context.user_data["cl_from_project"] = context.user_data.get("cl_from_project", False)

    await query.edit_message_text(
        t(lang, "clients.enter_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="cl:cancel")]
        ])
    )
    return CL_CREATE_NAME


async def create_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    context.user_data["cl_name"] = update.message.text.strip()

    await update.message.reply_text(
        t(lang, "clients.enter_phone"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.skip"), callback_data="cl:skip_phone")],
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="cl:cancel")],
        ])
    )
    return CL_CREATE_PHONE


async def create_client_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    context.user_data["cl_phone"] = update.message.text.strip()
    return await _finish_client_create(update, context)


async def create_client_skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["cl_phone"] = None
    return await _finish_client_create(update, context)


async def _finish_client_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    name = context.user_data["cl_name"]
    phone = context.user_data.get("cl_phone")

    async with async_session() as session:
        client = Client(
            director_id=info["director_id"],
            name=name,
            phone=phone,
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        client_id = client.id

    msg = update.effective_message or update.callback_query.message
    await msg.reply_text(t(lang, "clients.created", name=name))

    # If creating from project flow — return to project creation with client selected
    if context.user_data.get("cl_from_project"):
        context.user_data["cl_from_project"] = False
        context.user_data["pj_client_id"] = client_id
        context.user_data["pj_client_name"] = name
        from handlers.projects import _continue_project_creation
        return await _continue_project_creation(update, context)

    await show_clients_menu(update, context)
    return ConversationHandler.END


async def create_client_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["cl_from_project"] = False
    await show_clients_menu(update, context)
    return ConversationHandler.END


# ─── Rename client ───

async def rename_client_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    context.user_data["info"] = info
    lang = info["lang"]
    client_id = int(query.data.split(":")[2])
    context.user_data["cl_rename_id"] = client_id

    await query.edit_message_text(
        t(lang, "clients.enter_new_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"cl:view:{client_id}")]
        ])
    )
    return CL_RENAME


async def rename_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    new_name = update.message.text.strip()
    client_id = context.user_data["cl_rename_id"]

    async with async_session() as session:
        result = await session.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one()
        client.name = new_name
        await session.commit()

    await update.message.reply_text(t(lang, "clients.renamed", name=new_name))
    await show_clients_menu(update, context)
    return ConversationHandler.END


async def rename_client_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await view_client(update, context)
    return ConversationHandler.END


# ─── Delete client ───

async def delete_client_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    context.user_data["info"] = info
    lang = info["lang"]
    client_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one()

    await query.edit_message_text(
        t(lang, "clients.confirm_delete", name=client.name),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(t(lang, "btn.confirm"), callback_data=f"cl:del_yes:{client_id}"),
                InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"cl:view:{client_id}"),
            ]
        ])
    )


async def delete_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    context.user_data["info"] = info
    lang = info["lang"]
    client_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one()
        client.is_active = False
        await session.commit()
        name = client.name

    await query.edit_message_text(t(lang, "clients.deleted", name=name))
    await show_clients_menu(update, context)


def get_clients_handlers():
    create_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_client_start, pattern=r"^cl:create$")],
        states={
            CL_CREATE_NAME: [
                CallbackQueryHandler(create_client_cancel, pattern=r"^cl:cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_client_name),
            ],
            CL_CREATE_PHONE: [
                CallbackQueryHandler(create_client_cancel, pattern=r"^cl:cancel$"),
                CallbackQueryHandler(create_client_skip_phone, pattern=r"^cl:skip_phone$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_client_phone),
            ],
        },
        fallbacks=[CallbackQueryHandler(create_client_cancel, pattern=r"^cl:cancel$")],
        per_message=False,
    )

    rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rename_client_start, pattern=r"^cl:rename:\d+$")],
        states={
            CL_RENAME: [
                CallbackQueryHandler(rename_client_cancel, pattern=r"^cl:view:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_client_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(rename_client_cancel, pattern=r"^cl:view:\d+$")],
        per_message=False,
    )

    return [
        create_conv,
        rename_conv,
        CallbackQueryHandler(view_client, pattern=r"^cl:view:\d+$"),
        CallbackQueryHandler(delete_client_confirm, pattern=r"^cl:delete:\d+$"),
        CallbackQueryHandler(delete_client, pattern=r"^cl:del_yes:\d+$"),
    ]
