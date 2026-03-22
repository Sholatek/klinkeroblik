from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from models import Director, Worker, BrigadeMember
from database import async_session
from utils.i18n import t


async def get_user_info(telegram_id: int) -> dict | None:
    """Returns dict with role, lang, director_id, worker_id, brigade_id or None."""
    async with async_session() as session:
        # Check if director
        result = await session.execute(
            select(Director).where(Director.telegram_id == telegram_id)
        )
        director = result.scalar_one_or_none()
        if director:
            return {
                "role": "director",
                "lang": director.language,
                "currency": director.currency,
                "director_id": director.id,
                "worker_id": None,
                "brigade_id": None,
                "user_id": director.id,
                "name": director.name,
            }
        # Check if worker
        result = await session.execute(
            select(Worker).where(Worker.telegram_id == telegram_id, Worker.is_active == True)
        )
        worker = result.scalar_one_or_none()
        if worker:
            # Get brigade membership and role
            result = await session.execute(
                select(BrigadeMember).where(
                    BrigadeMember.worker_id == worker.id,
                    BrigadeMember.is_active == True,
                )
            )
            member = result.scalar_one_or_none()
            # Get director's currency
            result = await session.execute(
                select(Director).where(Director.id == worker.director_id)
            )
            director = result.scalar_one_or_none()
            return {
                "role": member.role if member else "worker",
                "lang": worker.language,
                "currency": director.currency if director else "PLN",
                "director_id": worker.director_id,
                "worker_id": worker.id,
                "brigade_id": member.brigade_id if member else None,
                "user_id": worker.id,
                "name": worker.name,
            }
    return None


def require_registration(func):
    """Decorator: user must be registered."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        info = await get_user_info(tg_id)
        if not info:
            await update.effective_message.reply_text(
                "⚠️ Please register first: /start"
            )
            return
        context.user_data["info"] = info
        return await func(update, context)
    return wrapper


def director_only(func):
    """Decorator: only directors can use this."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        info = await get_user_info(tg_id)
        if not info or info["role"] != "director":
            lang = info["lang"] if info else "uk"
            await update.effective_message.reply_text(t(lang, "errors.director_only"))
            return
        context.user_data["info"] = info
        return await func(update, context)
    return wrapper


def brigadier_or_director(func):
    """Decorator: brigadiers and directors can use this."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        info = await get_user_info(tg_id)
        if not info or info["role"] not in ("director", "brigadier"):
            lang = info["lang"] if info else "uk"
            await update.effective_message.reply_text(t(lang, "errors.no_permission"))
            return
        context.user_data["info"] = info
        return await func(update, context)
    return wrapper
