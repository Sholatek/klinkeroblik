import logging
import string
import random
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import async_session
from models import Brigade, BrigadeMember, Worker, InviteCode
from utils.i18n import t
from utils.permissions import get_user_info
from config import INVITE_CODE_EXPIRY_DAYS

logger = logging.getLogger(__name__)

BR_CREATE_NAME = 200
BR_INVITE_ROLE = 201
BR_RENAME = 202


def _generate_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return f"KL-{''.join(random.choices(chars, k=4))}"


async def show_brigades_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]
    role = info["role"]

    async with async_session() as session:
        if role == "director":
            result = await session.execute(
                select(Brigade).where(
                    Brigade.director_id == info["director_id"],
                    Brigade.is_active == True,
                ).order_by(Brigade.name)
            )
        else:
            result = await session.execute(
                select(Brigade).where(
                    Brigade.id == info.get("brigade_id"),
                    Brigade.is_active == True,
                )
            )
        brigades = result.scalars().all()

    if not brigades:
        buttons = []
        if role == "director":
            buttons.append([InlineKeyboardButton(t(lang, "brigades.create"), callback_data="br:create")])
        buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])
        text = t(lang, "brigades.no_brigades")
    else:
        buttons = [[InlineKeyboardButton(f"👷 {b.name}", callback_data=f"br:view:{b.id}")]
                    for b in brigades]
        if role == "director":
            buttons.append([InlineKeyboardButton(t(lang, "brigades.create"), callback_data="br:create")])
        buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])
        text = t(lang, "brigades.title")

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def view_brigade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    brigade_id = int(query.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(
            select(Brigade).where(Brigade.id == brigade_id)
        )
        brigade = result.scalar_one()

        result = await session.execute(
            select(BrigadeMember)
            .options(selectinload(BrigadeMember.worker))
            .where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.is_active == True,
            )
        )
        members = result.scalars().all()

    lines = [t(lang, "brigades.members", name=brigade.name), ""]

    buttons = []
    for m in members:
        role_emoji = "👷‍♂️" if m.role == "brigadier" else "🧑‍🔧"
        role_name = t(lang, f"registration.role_{m.role}")
        label = f"{role_emoji} {m.worker.name} — {role_name}"
        lines.append(label)
        if info["role"] == "director":
            buttons.append([InlineKeyboardButton(
                f"⚙️ {m.worker.name}",
                callback_data=f"br:member:{brigade_id}:{m.worker_id}"
            )])

    if not members:
        lines.append("—")

    buttons.append([InlineKeyboardButton(t(lang, "brigades.invite"), callback_data=f"br:invite:{brigade_id}")])
    buttons.append([InlineKeyboardButton(t(lang, "brigades.add_existing"), callback_data=f"br:add_existing:{brigade_id}")])
    if info["role"] == "director":
        buttons.append([InlineKeyboardButton(t(lang, "brigades.rename"), callback_data=f"br:rename:{brigade_id}")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:brigades")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def create_brigade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info")
    lang = info["lang"]
    await query.edit_message_text(
        t(lang, "brigades.enter_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="menu:brigades")]
        ])
    )
    return BR_CREATE_NAME


async def create_brigade_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    name = update.message.text.strip()

    async with async_session() as session:
        brigade = Brigade(
            director_id=info["director_id"],
            name=name,
        )
        session.add(brigade)
        await session.commit()

    await update.message.reply_text(t(lang, "brigades.created", name=name))
    await show_brigades_menu(update, context)
    return ConversationHandler.END


async def create_brigade_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_brigades_menu(update, context)
    return ConversationHandler.END


async def invite_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info")
    lang = info["lang"]
    brigade_id = int(query.data.split(":")[2])
    context.user_data["invite_brigade_id"] = brigade_id

    buttons = [
        [InlineKeyboardButton(t(lang, "registration.role_brigadier"), callback_data="br:inv_role:brigadier")],
        [InlineKeyboardButton(t(lang, "registration.role_worker"), callback_data="br:inv_role:worker")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")],
    ]

    await query.edit_message_text(
        t(lang, "brigades.invite_role"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def invite_role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data["info"]
    lang = info["lang"]
    role = query.data.split(":")[2]
    brigade_id = context.user_data["invite_brigade_id"]

    code = _generate_code()
    expires = datetime.utcnow() + timedelta(days=INVITE_CODE_EXPIRY_DAYS)

    async with async_session() as session:
        # Ensure unique code
        while True:
            result = await session.execute(
                select(InviteCode).where(InviteCode.code == code)
            )
            if not result.scalar_one_or_none():
                break
            code = _generate_code()

        invite = InviteCode(
            code=code,
            director_id=info["director_id"],
            brigade_id=brigade_id,
            role=role,
            created_by_type=info["role"],
            created_by_id=info.get("director_id") if info["role"] == "director" else info.get("worker_id"),
            expires_at=expires,
        )
        session.add(invite)
        await session.commit()

        result = await session.execute(
            select(Brigade).where(Brigade.id == brigade_id)
        )
        brigade = result.scalar_one()

    role_text = t(lang, f"registration.role_{role}")
    expires_str = expires.strftime("%d.%m.%y")

    await query.edit_message_text(
        t(lang, "brigades.invite_created",
          code=code, role=role_text,
          brigade=brigade.name,
          expires=expires_str),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
        ])
    )

    # Send a separate plain-text message ready to forward to the worker
    await query.message.reply_text(
        t(lang, "brigades.invite_message",
          code=code,
          brigade=brigade.name,
          expires=expires_str),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
        ])
    )


async def rename_brigade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info")
    lang = info["lang"]
    brigade_id = int(query.data.split(":")[2])
    context.user_data["rename_brigade_id"] = brigade_id
    await query.edit_message_text(
        t(lang, "brigades.enter_new_name"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"br:view:{brigade_id}")]
        ])
    )
    return BR_RENAME


async def rename_brigade_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    new_name = update.message.text.strip()
    brigade_id = context.user_data["rename_brigade_id"]

    async with async_session() as session:
        result = await session.execute(select(Brigade).where(Brigade.id == brigade_id))
        brigade = result.scalar_one()
        brigade.name = new_name
        await session.commit()

    await update.message.reply_text(t(lang, "brigades.renamed", name=new_name))
    await show_brigades_menu(update, context)
    return ConversationHandler.END


async def rename_brigade_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel rename and return to brigade view."""
    await view_brigade(update, context)
    return ConversationHandler.END


# ─── Member management ───

async def view_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show member options: transfer or remove."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    parts = query.data.split(":")
    brigade_id = int(parts[2])
    worker_id = int(parts[3])
    context.user_data["br_member_brigade_id"] = brigade_id
    context.user_data["br_member_worker_id"] = worker_id

    async with async_session() as session:
        result = await session.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one()
        result = await session.execute(
            select(BrigadeMember).where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.worker_id == worker_id,
                BrigadeMember.is_active == True,
            )
        )
        member = result.scalar_one_or_none()
        role_name = t(lang, f"registration.role_{member.role}") if member else ""
        role_emoji = "👷‍♂️" if member and member.role == "brigadier" else "🧑‍🔧"

    buttons = [
        [InlineKeyboardButton(t(lang, "brigades.change_role"), callback_data=f"br:change_role:{brigade_id}:{worker_id}")],
        [InlineKeyboardButton(t(lang, "brigades.transfer"), callback_data=f"br:transfer:{worker_id}")],
        [InlineKeyboardButton(t(lang, "brigades.remove_member"), callback_data=f"br:remove_confirm:{worker_id}")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")],
    ]

    await query.edit_message_text(
        f"{role_emoji} {worker.name} — {role_name}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def add_existing_worker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of workers not currently in this brigade."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    brigade_id = int(query.data.split(":")[2])

    async with async_session() as session:
        # Get worker IDs already active in this brigade
        result = await session.execute(
            select(BrigadeMember.worker_id).where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.is_active == True,
            )
        )
        active_worker_ids = {row[0] for row in result.all()}

        # Get all workers under this director
        result = await session.execute(
            select(Worker).where(
                Worker.director_id == info["director_id"],
                Worker.is_active == True,
            ).order_by(Worker.name)
        )
        all_workers = result.scalars().all()

    # Filter to workers NOT in this brigade
    available = [w for w in all_workers if w.id not in active_worker_ids]

    if not available:
        await query.edit_message_text(
            t(lang, "brigades.no_available_workers"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
            ])
        )
        return

    buttons = [[InlineKeyboardButton(f"👷 {w.name}", callback_data=f"br:readd:{brigade_id}:{w.id}")]
               for w in available]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")])

    await query.edit_message_text(
        t(lang, "brigades.select_worker_to_add"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def readd_worker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-add an existing worker to the brigade."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    parts = query.data.split(":")
    brigade_id = int(parts[2])
    worker_id = int(parts[3])

    async with async_session() as session:
        # Check if there's an inactive membership to reactivate
        result = await session.execute(
            select(BrigadeMember).where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.worker_id == worker_id,
                BrigadeMember.is_active == False,
            )
        )
        old_member = result.scalar_one_or_none()

        if old_member:
            old_member.is_active = True
        else:
            session.add(BrigadeMember(
                brigade_id=brigade_id,
                worker_id=worker_id,
                role="worker",
            ))
        await session.commit()

        result = await session.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one()

    await query.edit_message_text(
        t(lang, "brigades.worker_added", name=worker.name),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
        ])
    )


# ─── Member management ───

async def change_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle worker role between worker and brigadier."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    parts = query.data.split(":")
    brigade_id = int(parts[2])
    worker_id = int(parts[3])

    async with async_session() as session:
        result = await session.execute(
            select(BrigadeMember).where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.worker_id == worker_id,
                BrigadeMember.is_active == True,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return

        # Toggle role
        new_role = "brigadier" if member.role == "worker" else "worker"
        member.role = new_role
        await session.commit()

        result = await session.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one()

    role_name = t(lang, f"registration.role_{new_role}")
    await query.edit_message_text(
        t(lang, "brigades.role_changed", name=worker.name, role=role_name),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
        ])
    )


async def transfer_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of other brigades to transfer the worker to."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    worker_id = int(query.data.split(":")[2])
    current_brigade_id = context.user_data["br_member_brigade_id"]

    async with async_session() as session:
        result = await session.execute(
            select(Brigade).where(
                Brigade.director_id == info["director_id"],
                Brigade.is_active == True,
                Brigade.id != current_brigade_id,
            ).order_by(Brigade.name)
        )
        brigades = result.scalars().all()

    if not brigades:
        await query.edit_message_text(
            t(lang, "brigades.no_other_brigades"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:member:{current_brigade_id}:{worker_id}")]
            ])
        )
        return

    buttons = [[InlineKeyboardButton(b.name, callback_data=f"br:transfer_to:{worker_id}:{b.id}")]
               for b in brigades]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:member:{current_brigade_id}:{worker_id}")])

    await query.edit_message_text(
        t(lang, "brigades.select_target_brigade"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def transfer_to_brigade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute the transfer."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    parts = query.data.split(":")
    worker_id = int(parts[2])
    new_brigade_id = int(parts[3])
    old_brigade_id = context.user_data["br_member_brigade_id"]

    async with async_session() as session:
        # Deactivate old membership
        result = await session.execute(
            select(BrigadeMember).where(
                BrigadeMember.worker_id == worker_id,
                BrigadeMember.brigade_id == old_brigade_id,
                BrigadeMember.is_active == True,
            )
        )
        old_member = result.scalar_one_or_none()
        if old_member:
            old_member.is_active = False

        # Create new membership
        new_member = BrigadeMember(
            brigade_id=new_brigade_id,
            worker_id=worker_id,
            role="worker",
        )
        session.add(new_member)
        await session.commit()

        # Get names
        result = await session.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one()
        result = await session.execute(select(Brigade).where(Brigade.id == new_brigade_id))
        new_brigade = result.scalar_one()

    await query.edit_message_text(
        t(lang, "brigades.transferred", name=worker.name, brigade=new_brigade.name),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{old_brigade_id}")]
        ])
    )


async def remove_member_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    worker_id = int(query.data.split(":")[2])
    brigade_id = context.user_data["br_member_brigade_id"]

    async with async_session() as session:
        result = await session.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one()

    await query.edit_message_text(
        t(lang, "brigades.confirm_remove", name=worker.name),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(t(lang, "btn.confirm"), callback_data=f"br:remove_yes:{worker_id}"),
                InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"br:member:{brigade_id}:{worker_id}"),
            ]
        ])
    )


async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    worker_id = int(query.data.split(":")[2])
    brigade_id = context.user_data["br_member_brigade_id"]

    async with async_session() as session:
        result = await session.execute(
            select(BrigadeMember).where(
                BrigadeMember.worker_id == worker_id,
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.is_active == True,
            )
        )
        member = result.scalar_one_or_none()
        if member:
            member.is_active = False
            await session.commit()

        result = await session.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one()

    await query.edit_message_text(
        t(lang, "brigades.removed", name=worker.name),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
        ])
    )


def get_brigades_handlers():
    create_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_brigade_start, pattern=r"^br:create$")],
        states={
            BR_CREATE_NAME: [
                CallbackQueryHandler(create_brigade_cancel, pattern=r"^menu:brigades$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_brigade_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(create_brigade_cancel, pattern=r"^menu:brigades$")],
        per_message=False,
    )
    rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rename_brigade_start, pattern=r"^br:rename:\d+$")],
        states={
            BR_RENAME: [
                CallbackQueryHandler(rename_brigade_cancel, pattern=r"^br:view:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_brigade_name),
            ],
        },
        fallbacks=[CallbackQueryHandler(rename_brigade_cancel, pattern=r"^br:view:\d+$")],
        per_message=False,
    )
    return [
        create_conv,
        rename_conv,
        CallbackQueryHandler(view_brigade, pattern=r"^br:view:\d+$"),
        CallbackQueryHandler(invite_start, pattern=r"^br:invite:\d+$"),
        CallbackQueryHandler(invite_role_selected, pattern=r"^br:inv_role:(brigadier|worker)$"),
        CallbackQueryHandler(view_member, pattern=r"^br:member:\d+:\d+$"),
        CallbackQueryHandler(add_existing_worker, pattern=r"^br:add_existing:\d+$"),
        CallbackQueryHandler(readd_worker, pattern=r"^br:readd:\d+:\d+$"),
        CallbackQueryHandler(change_role, pattern=r"^br:change_role:\d+:\d+$"),
        CallbackQueryHandler(transfer_member, pattern=r"^br:transfer:\d+$"),
        CallbackQueryHandler(transfer_to_brigade, pattern=r"^br:transfer_to:\d+:\d+$"),
        CallbackQueryHandler(remove_member_confirm, pattern=r"^br:remove_confirm:\d+$"),
        CallbackQueryHandler(remove_member, pattern=r"^br:remove_yes:\d+$"),
    ]
