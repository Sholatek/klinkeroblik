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
    for m in members:
        role_emoji = "👷‍♂️" if m.role == "brigadier" else "🧑‍🔧"
        role_name = t(lang, f"registration.role_{m.role}")
        lines.append(t(lang, "brigades.member_line",
                       role_emoji=role_emoji, name=m.worker.name, role=role_name))

    if not members:
        lines.append("—")

    buttons = [
        [InlineKeyboardButton(t(lang, "brigades.invite"), callback_data=f"br:invite:{brigade_id}")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:brigades")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def create_brigade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info")
    lang = info["lang"]
    await query.edit_message_text(t(lang, "brigades.enter_name"))
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
    await query.edit_message_text(
        t(lang, "brigades.invite_created",
          code=code, role=role_text,
          brigade=brigade.name,
          expires=expires.strftime("%d.%m.%Y")),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data=f"br:view:{brigade_id}")]
        ])
    )


def get_brigades_handlers():
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_brigade_start, pattern=r"^br:create$")],
        states={
            BR_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_brigade_name)],
        },
        fallbacks=[],
        per_message=False,
    )
    return [
        conv,
        CallbackQueryHandler(view_brigade, pattern=r"^br:view:\d+$"),
        CallbackQueryHandler(invite_start, pattern=r"^br:invite:\d+$"),
        CallbackQueryHandler(invite_role_selected, pattern=r"^br:inv_role:(brigadier|worker)$"),
    ]
