import logging
from datetime import date, timedelta, datetime
from decimal import Decimal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import async_session
from models import (
    WorkEntry, WorkEntryItem, WorkType, Worker, Brigade,
    BrigadeMember, Element, Building, Project, Director,
)
from utils.i18n import t, unit_label, currency_symbol
from utils.permissions import get_user_info

logger = logging.getLogger(__name__)


async def show_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]
    role = info["role"]

    buttons = [
        [InlineKeyboardButton(t(lang, "reports.today"), callback_data="rep:today")],
        [InlineKeyboardButton(t(lang, "reports.week"), callback_data="rep:week")],
        [InlineKeyboardButton(t(lang, "reports.month"), callback_data="rep:month")],
    ]
    if role in ("director", "brigadier"):
        buttons.append([InlineKeyboardButton(t(lang, "reports.by_brigade"), callback_data="rep:brigade")])
    if role == "director":
        buttons.append([InlineKeyboardButton(t(lang, "reports.by_project"), callback_data="rep:project")])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            t(lang, "reports.title"), reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            t(lang, "reports.title"), reply_markup=InlineKeyboardMarkup(buttons)
        )


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    action = query.data.split(":")[1]

    today = date.today()

    if action == "today":
        await _generate_personal_report(update, context, today, today)
    elif action == "week":
        start = today - timedelta(days=today.weekday())
        await _generate_personal_report(update, context, start, today)
    elif action == "month":
        start = today.replace(day=1)
        await _generate_personal_report(update, context, start, today)
    elif action == "brigade":
        await _generate_brigade_report(update, context, today - timedelta(days=today.weekday()), today)
    elif action == "project":
        await _show_project_selector_for_report(update, context)


async def _generate_personal_report(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                     start_date: date, end_date: date) -> None:
    info = context.user_data["info"]
    lang = info["lang"]

    # Get worker_id
    worker_id = info.get("worker_id")
    if not worker_id and info["role"] == "director":
        async with async_session() as session:
            result = await session.execute(
                select(Worker).where(Worker.telegram_id == update.effective_user.id)
            )
            w = result.scalar_one_or_none()
            if w:
                worker_id = w.id

    if not worker_id:
        await update.callback_query.edit_message_text(
            t(lang, "reports.no_data"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]
            ])
        )
        return

    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        curr_sym = currency_symbol(director.currency)

        result = await session.execute(
            select(WorkEntry)
            .options(
                selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type),
                selectinload(WorkEntry.element)
                .selectinload(Element.building)
                .selectinload(Building.project),
            )
            .where(
                WorkEntry.worker_id == worker_id,
                WorkEntry.work_date >= start_date,
                WorkEntry.work_date <= end_date,
            )
            .order_by(WorkEntry.work_date)
        )
        entries = result.scalars().all()

    if not entries:
        await update.callback_query.edit_message_text(
            t(lang, "reports.no_data"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]
            ])
        )
        return

    lines = [
        t(lang, "reports.period",
          start=start_date.strftime("%d.%m.%Y"),
          end=end_date.strftime("%d.%m.%Y")),
        "",
    ]

    grand_total = Decimal("0")
    for entry in entries:
        elem = entry.element
        bld = elem.building
        proj = bld.project
        lines.append(f"📅 {entry.work_date.strftime('%d.%m.%Y')}")
        lines.append(f"📍 {proj.name} → {bld.name} → {elem.name}")
        for item in entry.items:
            wt = item.work_type
            ul = unit_label(wt.unit, lang)
            lines.append(f"  {wt.get_name(lang)}: {item.quantity:.2f} {ul} × "
                         f"{item.rate_applied:.2f} {curr_sym} = {item.total:.2f} {curr_sym}")
            grand_total += item.total
        lines.append("")

    lines.append(t(lang, "reports.total_earned",
                   total=f"{grand_total:.2f}", currency=curr_sym))

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]
        ])
    )


async def _generate_brigade_report(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                    start_date: date, end_date: date) -> None:
    info = context.user_data["info"]
    lang = info["lang"]
    role = info["role"]

    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        curr_sym = currency_symbol(director.currency)

        # Get brigades
        if role == "director":
            result = await session.execute(
                select(Brigade).where(
                    Brigade.director_id == info["director_id"],
                    Brigade.is_active == True,
                )
            )
            brigades = result.scalars().all()
        else:
            brigades_result = await session.execute(
                select(Brigade).where(Brigade.id == info.get("brigade_id"))
            )
            brigades = brigades_result.scalars().all()

        lines = [
            t(lang, "reports.period",
              start=start_date.strftime("%d.%m.%Y"),
              end=end_date.strftime("%d.%m.%Y")),
            "",
        ]

        grand_total = Decimal("0")

        for brigade in brigades:
            result = await session.execute(
                select(BrigadeMember)
                .options(selectinload(BrigadeMember.worker))
                .where(
                    BrigadeMember.brigade_id == brigade.id,
                    BrigadeMember.is_active == True,
                )
            )
            members = result.scalars().all()

            brigade_total = Decimal("0")
            brigade_lines = []

            for member in members:
                worker = member.worker
                result = await session.execute(
                    select(WorkEntry)
                    .options(selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type))
                    .where(
                        WorkEntry.worker_id == worker.id,
                        WorkEntry.work_date >= start_date,
                        WorkEntry.work_date <= end_date,
                    )
                )
                entries = result.scalars().all()
                worker_total = sum(
                    item.total for entry in entries for item in entry.items
                )
                if entries:
                    role_emoji = "👷‍♂️" if member.role == "brigadier" else "🧑‍🔧"
                    brigade_lines.append(f"  {role_emoji} {worker.name}: {worker_total:.2f} {curr_sym}")
                    brigade_total += worker_total

            if brigade_lines:
                lines.append(f"👷 {brigade.name}:")
                lines.extend(brigade_lines)
                lines.append(t(lang, "reports.brigade_total", name=brigade.name))
                lines.append(f"  💰 {brigade_total:.2f} {curr_sym}")
                lines.append("")
                grand_total += brigade_total

        lines.append(t(lang, "reports.total_earned",
                       total=f"{grand_total:.2f}", currency=curr_sym))

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]
        ])
    )


async def _show_project_selector_for_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data["info"]
    lang = info["lang"]

    async with async_session() as session:
        result = await session.execute(
            select(Project).where(
                Project.director_id == info["director_id"],
                Project.is_active == True,
            ).order_by(Project.name)
        )
        projects = result.scalars().all()

    buttons = [[InlineKeyboardButton(p.name, callback_data=f"rep_proj:{p.id}")]
               for p in projects]
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")])

    await update.callback_query.edit_message_text(
        t(lang, "reports.by_project"),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def project_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    lang = info["lang"]
    project_id = int(query.data.split(":")[1])

    today = date.today()
    start_date = today - timedelta(days=today.weekday())

    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == info["director_id"])
        )
        director = result.scalar_one()
        curr_sym = currency_symbol(director.currency)

        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one()

        # Get all entries for this project
        result = await session.execute(
            select(WorkEntry)
            .options(
                selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type),
                selectinload(WorkEntry.worker),
                selectinload(WorkEntry.element)
                .selectinload(Element.building),
            )
            .join(Element).join(Building)
            .where(
                Building.project_id == project_id,
                WorkEntry.work_date >= start_date,
                WorkEntry.work_date <= today,
            )
            .order_by(WorkEntry.work_date)
        )
        entries = result.scalars().all()

    if not entries:
        await query.edit_message_text(
            t(lang, "reports.no_data"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]
            ])
        )
        return

    lines = [
        f"🏗️ {project.name}",
        t(lang, "reports.period",
          start=start_date.strftime("%d.%m.%Y"),
          end=today.strftime("%d.%m.%Y")),
        "",
    ]

    grand_total = Decimal("0")
    for entry in entries:
        worker = entry.worker
        elem = entry.element
        bld = elem.building
        lines.append(f"📅 {entry.work_date.strftime('%d.%m.%Y')} — {worker.name}")
        lines.append(f"  📍 {bld.name} → {elem.name}")
        for item in entry.items:
            wt = item.work_type
            ul = unit_label(wt.unit, lang)
            lines.append(f"  {wt.get_name(lang)}: {item.quantity:.2f} {ul} = {item.total:.2f} {curr_sym}")
            grand_total += item.total
        lines.append("")

    lines.append(t(lang, "reports.total_earned",
                   total=f"{grand_total:.2f}", currency=curr_sym))

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]
        ])
    )


def get_reports_handlers():
    return [
        CallbackQueryHandler(report_callback, pattern=r"^rep:(today|week|month|brigade|project)$"),
        CallbackQueryHandler(project_report_callback, pattern=r"^rep_proj:\d+$"),
    ]
