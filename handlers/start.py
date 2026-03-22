import logging
import string
import random
from datetime import datetime, timedelta
from decimal import Decimal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters,
)
from sqlalchemy import select

from database import async_session
from models import Director, Worker, Brigade, BrigadeMember, InviteCode, WorkType
from utils.i18n import t
from utils.keyboards import language_keyboard, role_keyboard, main_menu_keyboard, skip_keyboard
from config import INVITE_CODE_EXPIRY_DAYS

logger = logging.getLogger(__name__)

# Conversation states
LANG, ROLE, NAME, COMPANY, INVITE_CODE, INVITE_NAME = range(6)

DEFAULT_WORK_TYPES = [
    ("Укладання плитки", "Układanie płytek", "Укладка плитки", "m2", Decimal("60.00"), 1),
    ("Погонні роботи", "Prace liniowe", "Погонные работы", "mp", Decimal("30.00"), 2),
    ("Підрізка під 45°", "Cięcie pod kątem 45°", "Подрезка под 45°", "mp", Decimal("0.00"), 3),
    ("Прорізка делатацій", "Cięcie dylatacji", "Прорезка делатаций", "mp", Decimal("0.00"), 4),
    ("Погодинна робота", "Praca godzinowa", "Почасовая работа", "h", Decimal("0.00"), 5),
    ("Фугування", "Fugowanie", "Фуговка", "m2", Decimal("0.00"), 6),
    ("Силікон", "Silikon", "Силикон", "mp", Decimal("0.00"), 7),
]


def generate_invite_code() -> str:
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choices(chars, k=4))
    return f"KL-{code}"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — check if registered, show language selection."""
    tg_id = update.effective_user.id

    async with async_session() as session:
        # Check director
        result = await session.execute(
            select(Director).where(Director.telegram_id == tg_id)
        )
        director = result.scalar_one_or_none()
        if director:
            from handlers.menu import show_main_menu
            context.user_data["info"] = {
                "role": "director", "lang": director.language,
                "currency": director.currency, "director_id": director.id,
                "name": director.name,
            }
            await show_main_menu(update, context)
            return ConversationHandler.END

        # Check worker
        result = await session.execute(
            select(Worker).where(Worker.telegram_id == tg_id, Worker.is_active == True)
        )
        worker = result.scalar_one_or_none()
        if worker:
            result = await session.execute(
                select(BrigadeMember).where(
                    BrigadeMember.worker_id == worker.id,
                    BrigadeMember.is_active == True
                )
            )
            member = result.scalar_one_or_none()
            from handlers.menu import show_main_menu
            context.user_data["info"] = {
                "role": member.role if member else "worker",
                "lang": worker.language,
                "director_id": worker.director_id,
                "worker_id": worker.id,
                "brigade_id": member.brigade_id if member else None,
                "name": worker.name,
            }
            await show_main_menu(update, context)
            return ConversationHandler.END

    # New user — choose language
    await update.message.reply_text(
        t("uk", "welcome"),
        reply_markup=language_keyboard()
    )
    return LANG


async def lang_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    lang = query.data.split(":")[1]
    context.user_data["lang"] = lang

    await query.edit_message_text(
        text=t(lang, "welcome").split("\n")[0],
        reply_markup=role_keyboard(lang)
    )
    return ROLE


async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    role = query.data.split(":")[1]
    lang = context.user_data.get("lang", "uk")

    if role == "director":
        context.user_data["reg_role"] = "director"
        await query.edit_message_text(t(lang, "registration.enter_name"))
        return NAME
    else:
        context.user_data["reg_role"] = "join"
        await query.edit_message_text(t(lang, "registration.enter_invite_code"))
        return INVITE_CODE


async def name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    lang = context.user_data.get("lang", "uk")
    reg_role = context.user_data.get("reg_role")

    if reg_role == "director":
        context.user_data["reg_name"] = name
        await update.message.reply_text(
            t(lang, "registration.enter_company"),
            reply_markup=skip_keyboard(lang)
        )
        return COMPANY
    else:
        # Worker/brigadier joining
        context.user_data["reg_name"] = name
        return await _finalize_join(update, context)


async def company_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip() if update.message else None
    lang = context.user_data.get("lang", "uk")

    if update.callback_query:
        await update.callback_query.answer()
        company = None
    else:
        company = text

    context.user_data["reg_company"] = company
    return await _finalize_director(update, context)


async def company_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["reg_company"] = None
    return await _finalize_director(update, context)


async def _finalize_director(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get("lang", "uk")
    name = context.user_data["reg_name"]
    company = context.user_data.get("reg_company")
    tg_id = update.effective_user.id
    tg_user = update.effective_user

    async with async_session() as session:
        director = Director(
            telegram_id=tg_id,
            name=name,
            phone=None,
            email=None,
            company_name=company,
            language=lang,
        )
        session.add(director)
        await session.flush()

        # Create default work types
        for name_uk, name_pl, name_ru, unit, rate, order in DEFAULT_WORK_TYPES:
            wt = WorkType(
                director_id=director.id,
                name_uk=name_uk, name_pl=name_pl, name_ru=name_ru,
                unit=unit, default_rate=rate, sort_order=order,
            )
            session.add(wt)

        await session.commit()

        context.user_data["info"] = {
            "role": "director", "lang": lang, "currency": "PLN",
            "director_id": director.id, "name": name,
        }

    msg = update.effective_message or update.callback_query.message
    await msg.reply_text(
        t(lang, "registration.success_director", name=name),
    )

    from handlers.menu import show_main_menu
    await show_main_menu(update, context, send_new=True)
    return ConversationHandler.END


async def invite_code_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    lang = context.user_data.get("lang", "uk")

    async with async_session() as session:
        result = await session.execute(
            select(InviteCode).where(
                InviteCode.code == code,
                InviteCode.used_by == None,
                InviteCode.expires_at > datetime.utcnow(),
            )
        )
        invite = result.scalar_one_or_none()

    if not invite:
        await update.message.reply_text(t(lang, "registration.invalid_code"))
        return INVITE_CODE

    context.user_data["invite"] = {
        "id": invite.id,
        "code": invite.code,
        "director_id": invite.director_id,
        "brigade_id": invite.brigade_id,
        "role": invite.role,
    }
    await update.message.reply_text(t(lang, "registration.enter_name"))
    return INVITE_NAME


async def invite_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["reg_name"] = update.message.text.strip()
    return await _finalize_join(update, context)


async def _finalize_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get("lang", "uk")
    name = context.user_data["reg_name"]
    invite_data = context.user_data.get("invite")
    tg_id = update.effective_user.id

    if not invite_data:
        await update.message.reply_text(t(lang, "errors.unknown"))
        return ConversationHandler.END

    async with async_session() as session:
        # Create worker
        worker = Worker(
            telegram_id=tg_id,
            director_id=invite_data["director_id"],
            name=name,
            language=lang,
        )
        session.add(worker)
        await session.flush()

        # Create brigade membership
        member = BrigadeMember(
            brigade_id=invite_data["brigade_id"],
            worker_id=worker.id,
            role=invite_data["role"],
        )
        session.add(member)

        # Mark invite as used
        result = await session.execute(
            select(InviteCode).where(InviteCode.id == invite_data["id"])
        )
        invite = result.scalar_one()
        invite.used_by = worker.id

        # Get brigade name
        result = await session.execute(
            select(Brigade).where(Brigade.id == invite_data["brigade_id"])
        )
        brigade = result.scalar_one()

        await session.commit()

        role_text = t(lang, f"registration.role_{invite_data['role']}")

        context.user_data["info"] = {
            "role": invite_data["role"], "lang": lang,
            "director_id": invite_data["director_id"],
            "worker_id": worker.id,
            "brigade_id": invite_data["brigade_id"],
            "name": name,
        }

    await update.message.reply_text(
        t(lang, "registration.success_worker",
          name=name, brigade=brigade.name, role=role_text)
    )

    from handlers.menu import show_main_menu
    await show_main_menu(update, context, send_new=True)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.get("lang", "uk")
    await update.message.reply_text(t(lang, "work.cancelled"))
    return ConversationHandler.END


def get_start_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            LANG: [CallbackQueryHandler(lang_selected, pattern=r"^lang:")],
            ROLE: [CallbackQueryHandler(role_selected, pattern=r"^role:")],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_entered)],
            COMPANY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, company_entered),
                CallbackQueryHandler(company_skipped, pattern=r"^skip$"),
            ],
            INVITE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, invite_code_entered)],
            INVITE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, invite_name_entered)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
