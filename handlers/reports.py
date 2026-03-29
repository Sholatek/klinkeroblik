import logging
import os
from datetime import date, timedelta, datetime
from decimal import Decimal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters,
)
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import async_session
from models import (
    WorkEntry, WorkEntryItem, WorkType, Worker, Brigade,
    BrigadeMember, Element, Building, Project, Director,
)
from utils.i18n import t, unit_label, currency_symbol
from utils.permissions import get_user_info
from utils.excel_export import generate_summary_excel, generate_project_excel, generate_totals_excel

logger = logging.getLogger(__name__)


def _parse_date(text: str) -> date:
    """Parse date from DD.MM.YY or DD.MM.YYYY format."""
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {text}")

# States for report conversation
REP_START_DATE, REP_END_DATE = 700, 701


async def show_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]
    role = info["role"]

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Quick period buttons
    buttons = [
        [InlineKeyboardButton(t(lang, "reports.today"), callback_data="rep:today")],
        [InlineKeyboardButton(
            t(lang, "reports.this_week") + f" ({week_start.strftime('%d.%m')}—{today.strftime('%d.%m')})",
            callback_data="rep:week")],
        [InlineKeyboardButton(
            t(lang, "reports.this_month") + f" ({month_start.strftime('%d.%m')}—{today.strftime('%d.%m')})",
            callback_data="rep:month")],
        [InlineKeyboardButton(t(lang, "reports.custom"), callback_data="rep:custom")],
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:main")],
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            t(lang, "reports.title"), reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            t(lang, "reports.title"), reply_markup=InlineKeyboardMarkup(buttons)
        )


async def report_period_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    action = query.data.split(":")[1]

    today = date.today()

    if action == "today":
        context.user_data["rep_start"] = today
        context.user_data["rep_end"] = today
        await _show_report_type_menu(update, context)
    elif action == "week":
        context.user_data["rep_start"] = today - timedelta(days=today.weekday())
        context.user_data["rep_end"] = today
        await _show_report_type_menu(update, context)
    elif action == "month":
        context.user_data["rep_start"] = today.replace(day=1)
        context.user_data["rep_end"] = today
        await _show_report_type_menu(update, context)


async def report_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return ConversationHandler.END
    context.user_data["info"] = info
    lang = info["lang"]

    await query.edit_message_text(
        t(lang, "reports.enter_start_date"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="rep:back_menu")]
        ])
    )
    return REP_START_DATE


async def report_start_date_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip()

    try:
        d = _parse_date(text)
        context.user_data["rep_start"] = d
        await update.message.reply_text(
            t(lang, "reports.enter_end_date"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="rep:back_menu")]
            ])
        )
        return REP_END_DATE
    except ValueError:
        await update.message.reply_text(t(lang, "work.invalid_date"))
        return REP_START_DATE


async def report_end_date_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    info = context.user_data["info"]
    lang = info["lang"]
    text = update.message.text.strip()

    try:
        d = _parse_date(text)
        context.user_data["rep_end"] = d
        await _show_report_type_menu(update, context)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(t(lang, "work.invalid_date"))
        return REP_END_DATE


async def report_custom_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_reports_menu(update, context)
    return ConversationHandler.END


async def _show_report_type_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """After period is selected — show report type options based on role."""
    info = context.user_data["info"]
    lang = info["lang"]
    role = info["role"]
    start = context.user_data["rep_start"]
    end = context.user_data["rep_end"]

    period_str = f"{start.strftime('%d.%m.%y')} — {end.strftime('%d.%m.%y')}"

    if role == "director":
        buttons = [
            [InlineKeyboardButton(t(lang, "reports.all"), callback_data="rept:summary")],
            [InlineKeyboardButton(t(lang, "reports.by_brigade"), callback_data="rept:brigade")],
            [InlineKeyboardButton(t(lang, "reports.by_project"), callback_data="rept:project")],
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")],
        ]
        text = f"📊 {period_str}\n\n{t(lang, 'reports.select_type')}"
    elif role == "brigadier":
        buttons = [
            [InlineKeyboardButton(t(lang, "reports.personal"), callback_data="rept:personal")],
            [InlineKeyboardButton(t(lang, "reports.my_brigade"), callback_data="rept:my_brigade")],
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")],
        ]
        text = f"📊 {period_str}\n\n{t(lang, 'reports.select_type')}"
    else:
        # Worker — just show personal summary
        buttons = [[InlineKeyboardButton(t(lang, "btn.back"), callback_data="menu:reports")]]
        text = await _build_worker_summary(info, lang, start, end)

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


async def report_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]

    start = context.user_data["rep_start"]
    end = context.user_data["rep_end"]
    action = query.data.split(":")[1]

    if action == "summary":
        text = await _build_total_summary(info, lang, start, end)
    elif action == "brigade":
        text = await _build_brigade_report(info, lang, start, end)
    elif action == "project":
        text = await _build_project_report(info, lang, start, end)
    elif action == "personal":
        # Brigadier personal — show as worker summary
        text = await _build_worker_summary(info, lang, start, end)
    elif action == "personal_projects":
        text = await _build_worker_by_project(info, lang, start, end)
    elif action == "my_brigade":
        text = await _build_my_brigade_summary(info, lang, start, end)
    elif action == "my_brigade_projects":
        text = await _build_my_brigade_by_project(info, lang, start, end)
    else:
        text = t(lang, "reports.no_data")

    if len(text) > 4000:
        text = text[:4000] + "\n..."

    # Sub-menu for personal and my_brigade
    if action == "personal":
        buttons = [
            [InlineKeyboardButton(t(lang, "reports.by_project"), callback_data="rept:personal_projects")],
            [InlineKeyboardButton(t(lang, "reports.download_excel"), callback_data=f"rept:excel:{action}")],
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="rept:back_type")],
        ]
    elif action == "my_brigade":
        buttons = [
            [InlineKeyboardButton(t(lang, "reports.by_project"), callback_data="rept:my_brigade_projects")],
            [InlineKeyboardButton(t(lang, "reports.download_excel"), callback_data=f"rept:excel:{action}")],
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="rept:back_type")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(t(lang, "reports.download_excel"), callback_data=f"rept:excel:{action}")],
            [InlineKeyboardButton(t(lang, "btn.back"), callback_data="rept:back_type")],
        ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ─── Report builders ───


async def _get_currency_symbol(director_id: int) -> str:
    async with async_session() as session:
        result = await session.execute(
            select(Director).where(Director.id == director_id)
        )
        director = result.scalar_one()
        return currency_symbol(director.currency)


async def _build_worker_summary(info: dict, lang: str, start: date, end: date) -> str:
    """Summary report for a worker: total meters + total earnings."""
    worker_id = info.get("worker_id")
    if not worker_id:
        return t(lang, "reports.no_data")

    curr_sym = await _get_currency_symbol(info["director_id"])

    async with async_session() as session:
        result = await session.execute(
            select(WorkEntry)
            .options(selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type))
            .where(
                WorkEntry.worker_id == worker_id,
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return t(lang, "reports.no_data")

    # Aggregate by work type
    totals = {}  # {wt_name: {unit, quantity, total}}
    grand_total = Decimal("0")

    for entry in entries:
        for item in entry.items:
            wt = item.work_type
            name = wt.get_name(lang)
            if name not in totals:
                totals[name] = {"unit": wt.unit, "quantity": Decimal("0"), "total": Decimal("0")}
            totals[name]["quantity"] += item.quantity
            totals[name]["total"] += item.total
            grand_total += item.total

    period_str = f"{start.strftime('%d.%m.%y')} — {end.strftime('%d.%m.%y')}"
    lines = [
        f"📊 {t(lang, 'reports.personal_summary')}",
        t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
        "",
    ]

    for name, data in totals.items():
        ul = unit_label(data["unit"], lang)
        lines.append(f"  {name}: {data['quantity']:.2f} {ul} = {data['total']:.2f} {curr_sym}")

    lines.append("")
    lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))

    return "\n".join(lines)


async def _build_total_summary(info: dict, lang: str, start: date, end: date) -> str:
    """Total summary for director: all work types aggregated (no worker breakdown)."""
    curr_sym = await _get_currency_symbol(info["director_id"])

    async with async_session() as session:
        result = await session.execute(
            select(Worker.id).where(Worker.director_id == info["director_id"])
        )
        worker_ids = [row[0] for row in result.all()]

        if not worker_ids:
            return t(lang, "reports.no_data")

        result = await session.execute(
            select(WorkEntry)
            .options(selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type))
            .where(
                WorkEntry.worker_id.in_(worker_ids),
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return t(lang, "reports.no_data")

    totals = {}
    grand_total = Decimal("0")
    for entry in entries:
        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            if tname not in totals:
                totals[tname] = {"unit": wt.unit, "quantity": Decimal("0"), "total": Decimal("0")}
            totals[tname]["quantity"] += item.quantity
            totals[tname]["total"] += item.total
            grand_total += item.total

    lines = [
        f"📊 {t(lang, 'reports.all')}",
        t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
        "",
    ]
    for tname, data in totals.items():
        ul = unit_label(data["unit"], lang)
        lines.append(f"  {tname}: {data['quantity']:.2f} {ul} = {data['total']:.2f} {curr_sym}")

    lines.append("")
    lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))

    return "\n".join(lines)


async def _build_brigade_report(info: dict, lang: str, start: date, end: date) -> str:
    """Report grouped by brigades."""
    curr_sym = await _get_currency_symbol(info["director_id"])

    async with async_session() as session:
        if info["role"] == "director":
            result = await session.execute(
                select(Brigade).where(
                    Brigade.director_id == info["director_id"],
                    Brigade.is_active == True,
                )
            )
            brigades = result.scalars().all()
        else:
            result = await session.execute(
                select(Brigade).where(Brigade.id == info.get("brigade_id"))
            )
            brigades = result.scalars().all()

        if not brigades:
            return t(lang, "reports.no_data")

        lines = [
            f"📊 {t(lang, 'reports.by_brigade')}",
            t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
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
                        WorkEntry.work_date >= start,
                        WorkEntry.work_date <= end,
                    )
                )
                w_entries = result.scalars().all()

                worker_total = Decimal("0")
                worker_types = {}
                for entry in w_entries:
                    for item in entry.items:
                        wt = item.work_type
                        tname = wt.get_name(lang)
                        if tname not in worker_types:
                            worker_types[tname] = {"unit": wt.unit, "qty": Decimal("0"), "total": Decimal("0")}
                        worker_types[tname]["qty"] += item.quantity
                        worker_types[tname]["total"] += item.total
                        worker_total += item.total

                if w_entries:
                    role_emoji = "👷‍♂️" if member.role == "brigadier" else "🧑‍🔧"
                    brigade_lines.append(f"  {role_emoji} {worker.name}: {worker_total:.2f} {curr_sym}")
                    for tname, tdata in worker_types.items():
                        ul = unit_label(tdata["unit"], lang)
                        brigade_lines.append(f"    {tname}: {tdata['qty']:.2f} {ul}")
                    brigade_total += worker_total

            if brigade_lines:
                lines.append(f"👷 {brigade.name}:")
                lines.extend(brigade_lines)
                lines.append(f"  💰 {t(lang, 'reports.brigade_total', name=brigade.name)} {brigade_total:.2f} {curr_sym}")
                lines.append("")
                grand_total += brigade_total

        if grand_total == 0:
            return t(lang, "reports.no_data")

        lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))

    return "\n".join(lines)


async def _build_project_report(info: dict, lang: str, start: date, end: date) -> str:
    """Report grouped by projects → buildings → elements."""
    curr_sym = await _get_currency_symbol(info["director_id"])

    async with async_session() as session:
        result = await session.execute(
            select(Project).where(
                Project.director_id == info["director_id"],
                Project.is_active == True,
            ).order_by(Project.name)
        )
        projects = result.scalars().all()

        if not projects:
            return t(lang, "reports.no_data")

        lines = [
            f"📊 {t(lang, 'reports.by_project')}",
            t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
            "",
        ]

        grand_total = Decimal("0")

        for project in projects:
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
                    Building.project_id == project.id,
                    WorkEntry.work_date >= start,
                    WorkEntry.work_date <= end,
                )
                .order_by(WorkEntry.work_date)
            )
            p_entries = result.scalars().all()

            if not p_entries:
                continue

            project_total = Decimal("0")
            lines.append(f"🏗️ {project.name}:")

            # Group: building → element → worker → work types
            structure = {}  # {bld_name: {elem_name: {worker_name: {wt_name: {unit, qty, total}}}}}
            for entry in p_entries:
                elem = entry.element
                bld = elem.building
                bld_key = bld.name if bld.name != "__default__" else None
                elem_key = elem.name if elem.name != "__default__" else None
                wname = entry.worker.name

                if bld_key not in structure:
                    structure[bld_key] = {}
                if elem_key not in structure[bld_key]:
                    structure[bld_key][elem_key] = {}
                if wname not in structure[bld_key][elem_key]:
                    structure[bld_key][elem_key][wname] = {}

                for item in entry.items:
                    wt = item.work_type
                    tname = wt.get_name(lang)
                    if tname not in structure[bld_key][elem_key][wname]:
                        structure[bld_key][elem_key][wname][tname] = {
                            "unit": wt.unit, "qty": Decimal("0"), "total": Decimal("0")
                        }
                    structure[bld_key][elem_key][wname][tname]["qty"] += item.quantity
                    structure[bld_key][elem_key][wname][tname]["total"] += item.total
                    project_total += item.total

            for bld_name, elems in structure.items():
                if bld_name:
                    lines.append(f"  🏠 {bld_name}:")
                    indent = "    "
                else:
                    indent = "  "

                for elem_name, workers in elems.items():
                    if elem_name:
                        lines.append(f"{indent}🧱 {elem_name}:")
                        w_indent = indent + "  "
                    else:
                        w_indent = indent

                    for wname, types in workers.items():
                        wtotal = sum(d["total"] for d in types.values())
                        lines.append(f"{w_indent}👷 {wname}: {wtotal:.2f} {curr_sym}")
                        for tname, tdata in types.items():
                            ul = unit_label(tdata["unit"], lang)
                            lines.append(f"{w_indent}  {tname}: {tdata['qty']:.2f} {ul} = {tdata['total']:.2f} {curr_sym}")

            lines.append(f"  💰 {project_total:.2f} {curr_sym}")
            lines.append("")
            grand_total += project_total

        if grand_total == 0:
            return t(lang, "reports.no_data")

        lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))

    return "\n".join(lines)


async def back_to_report_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Back from report result to report type selection."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    await _show_report_type_menu(update, context)


def _get_lang_labels(lang: str) -> dict:
    return {
        "summary": t(lang, "reports.all"),
        "by_project": t(lang, "reports.by_project"),
        "worker": "Працівник" if lang == "uk" else "Работник" if lang == "ru" else "Pracownik",
        "work_type": "Тип робіт" if lang == "uk" else "Тип работы" if lang == "ru" else "Typ pracy",
        "unit": "Од." if lang == "uk" else "Ед." if lang == "ru" else "Jed.",
        "quantity": "Кількість" if lang == "uk" else "Количество" if lang == "ru" else "Ilość",
        "total": "Сума" if lang == "uk" else "Сумма" if lang == "ru" else "Suma",
        "subtotal": "Підсумок" if lang == "uk" else "Итого" if lang == "ru" else "Razem",
        "grand_total": "ЗАГАЛОМ" if lang == "uk" else "ИТОГО" if lang == "ru" else "ŁĄCZNIE",
        "project": "Об'єкт" if lang == "uk" else "Объект" if lang == "ru" else "Obiekt",
    }


async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send Excel file for the current report."""
    query = update.callback_query
    await query.answer()
    info = context.user_data.get("info") or await get_user_info(update.effective_user.id)
    if not info:
        return
    context.user_data["info"] = info
    lang = info["lang"]
    start = context.user_data["rep_start"]
    end = context.user_data["rep_end"]

    action = query.data.split(":")[2]  # rept:excel:<action>
    curr_sym = await _get_currency_symbol(info["director_id"])
    lang_labels = _get_lang_labels(lang)

    file_path = None
    try:
        if action in ("summary", "my_brigade"):
            # Aggregated totals — no worker breakdown
            totals_data = await _get_totals_data(info, lang, start, end, action)
            if not totals_data:
                await query.message.reply_text(t(lang, "reports.no_data"))
                return
            title = t(lang, 'reports.all') if action == 'summary' else t(lang, 'reports.my_brigade')
            file_path = generate_totals_excel(title, start, end, totals_data, curr_sym, lang_labels)

        elif action == "personal":
            worker_data = await _get_summary_data(info, lang, start, end, action)
            if not worker_data:
                await query.message.reply_text(t(lang, "reports.no_data"))
                return
            title = t(lang, "reports.personal_summary")
            file_path = generate_summary_excel(title, start, end, worker_data, curr_sym, lang_labels)

        elif action in ("project", "personal_projects", "my_brigade_projects", "brigade"):
            project_data = await _get_project_data(info, lang, start, end, action)
            if not project_data:
                await query.message.reply_text(t(lang, "reports.no_data"))
                return
            title = t(lang, "reports.by_project")
            file_path = generate_project_excel(title, start, end, project_data, curr_sym, lang_labels)

        if file_path:
            filename = f"report_{action}_{start.strftime('%d%m%y')}-{end.strftime('%d%m%y')}.xlsx"
            with open(file_path, 'rb') as f:
                await query.message.reply_document(
                    document=f,
                    filename=filename,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t(lang, "btn.back"), callback_data="rept:back_type")]
                    ]),
                )
            os.unlink(file_path)

    except Exception as e:
        logger.error(f"Excel export error: {e}")
        await query.message.reply_text("⚠️ Error generating file")
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)


async def _get_totals_data(info, lang, start, end, action):
    """Get aggregated totals (no worker breakdown) for Excel export."""
    async with async_session() as session:
        if action == "summary":
            result = await session.execute(
                select(Worker.id).where(Worker.director_id == info["director_id"])
            )
            worker_ids = [row[0] for row in result.all()]
        elif action == "my_brigade":
            brigade_id = info.get("brigade_id")
            if not brigade_id:
                return {}
            result = await session.execute(
                select(BrigadeMember.worker_id).where(
                    BrigadeMember.brigade_id == brigade_id,
                    BrigadeMember.is_active == True,
                )
            )
            worker_ids = [row[0] for row in result.all()]
        else:
            return {}

        if not worker_ids:
            return {}

        result = await session.execute(
            select(WorkEntry)
            .options(selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type))
            .where(
                WorkEntry.worker_id.in_(worker_ids),
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return {}

    totals = {}
    for entry in entries:
        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            if tname not in totals:
                totals[tname] = {"unit": wt.unit, "quantity": Decimal("0"), "total": Decimal("0")}
            totals[tname]["quantity"] += item.quantity
            totals[tname]["total"] += item.total

    return totals


async def _get_summary_data(info, lang, start, end, action):
    """Get worker_data dict for summary excel export."""
    async with async_session() as session:
        if action == "summary":
            result = await session.execute(
                select(Worker.id).where(Worker.director_id == info["director_id"])
            )
            worker_ids = [row[0] for row in result.all()]
        elif action == "personal":
            worker_ids = [info["worker_id"]] if info.get("worker_id") else []
        elif action == "my_brigade":
            brigade_id = info.get("brigade_id")
            if not brigade_id:
                return {}
            result = await session.execute(
                select(BrigadeMember.worker_id).where(
                    BrigadeMember.brigade_id == brigade_id,
                    BrigadeMember.is_active == True,
                )
            )
            worker_ids = [row[0] for row in result.all()]
        else:
            return {}

        if not worker_ids:
            return {}

        result = await session.execute(
            select(WorkEntry)
            .options(
                selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type),
                selectinload(WorkEntry.worker),
            )
            .where(
                WorkEntry.worker_id.in_(worker_ids),
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return {}

    worker_data = {}
    for entry in entries:
        wname = entry.worker.name
        if wname not in worker_data:
            worker_data[wname] = {"types": {}, "total": Decimal("0")}
        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            if tname not in worker_data[wname]["types"]:
                worker_data[wname]["types"][tname] = {"unit": wt.unit, "quantity": Decimal("0"), "total": Decimal("0")}
            worker_data[wname]["types"][tname]["quantity"] += item.quantity
            worker_data[wname]["types"][tname]["total"] += item.total
            worker_data[wname]["total"] += item.total

    return worker_data


async def _get_project_data(info, lang, start, end, action):
    """Get project_data dict for project excel export."""
    async with async_session() as session:
        if action in ("project", "brigade"):
            result = await session.execute(
                select(Worker.id).where(Worker.director_id == info["director_id"])
            )
            worker_ids = [row[0] for row in result.all()]
        elif action == "personal_projects":
            worker_ids = [info["worker_id"]] if info.get("worker_id") else []
        elif action == "my_brigade_projects":
            brigade_id = info.get("brigade_id")
            if not brigade_id:
                return {}
            result = await session.execute(
                select(BrigadeMember.worker_id).where(
                    BrigadeMember.brigade_id == brigade_id,
                    BrigadeMember.is_active == True,
                )
            )
            worker_ids = [row[0] for row in result.all()]
        else:
            return {}

        if not worker_ids:
            return {}

        result = await session.execute(
            select(WorkEntry)
            .options(
                selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type),
                selectinload(WorkEntry.worker),
                selectinload(WorkEntry.element).selectinload(Element.building).selectinload(Building.project),
            )
            .where(
                WorkEntry.worker_id.in_(worker_ids),
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return {}

    project_data = {}
    for entry in entries:
        elem = entry.element
        bld = elem.building if elem else None
        proj = bld.project if bld else None
        proj_name = proj.name if proj else "—"
        bld_key = bld.name if bld and bld.name != "__default__" else None
        elem_key = elem.name if elem and elem.name != "__default__" else None
        wname = entry.worker.name

        if proj_name not in project_data:
            project_data[proj_name] = {}
        if bld_key not in project_data[proj_name]:
            project_data[proj_name][bld_key] = {}
        if elem_key not in project_data[proj_name][bld_key]:
            project_data[proj_name][bld_key][elem_key] = {}
        if wname not in project_data[proj_name][bld_key][elem_key]:
            project_data[proj_name][bld_key][elem_key][wname] = {"types": {}, "total": Decimal("0")}

        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            d = project_data[proj_name][bld_key][elem_key][wname]
            if tname not in d["types"]:
                d["types"][tname] = {"unit": wt.unit, "qty": Decimal("0"), "total": Decimal("0")}
            d["types"][tname]["qty"] += item.quantity
            d["types"][tname]["total"] += item.total
            d["total"] += item.total

    return project_data


async def _build_worker_by_project(info: dict, lang: str, start: date, end: date) -> str:
    """Personal report by project — for brigadier."""
    worker_id = info.get("worker_id")
    if not worker_id:
        return t(lang, "reports.no_data")

    curr_sym = await _get_currency_symbol(info["director_id"])

    async with async_session() as session:
        result = await session.execute(
            select(WorkEntry)
            .options(
                selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type),
                selectinload(WorkEntry.element).selectinload(Element.building).selectinload(Building.project),
            )
            .where(
                WorkEntry.worker_id == worker_id,
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return t(lang, "reports.no_data")

    # Group by project
    projects = {}
    grand_total = Decimal("0")
    for entry in entries:
        proj_name = entry.element.building.project.name if entry.element and entry.element.building else "—"
        if proj_name not in projects:
            projects[proj_name] = {"types": {}, "total": Decimal("0")}
        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            if tname not in projects[proj_name]["types"]:
                projects[proj_name]["types"][tname] = {"unit": wt.unit, "qty": Decimal("0"), "total": Decimal("0")}
            projects[proj_name]["types"][tname]["qty"] += item.quantity
            projects[proj_name]["types"][tname]["total"] += item.total
            projects[proj_name]["total"] += item.total
            grand_total += item.total

    lines = [
        f"📊 {t(lang, 'reports.personal_summary')} — {t(lang, 'reports.by_project')}",
        t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
        "",
    ]
    for pname, pdata in projects.items():
        lines.append(f"🏗️ {pname}: {pdata['total']:.2f} {curr_sym}")
        for tname, tdata in pdata["types"].items():
            ul = unit_label(tdata["unit"], lang)
            lines.append(f"  {tname}: {tdata['qty']:.2f} {ul} = {tdata['total']:.2f} {curr_sym}")
        lines.append("")

    lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))
    return "\n".join(lines)


async def _build_my_brigade_summary(info: dict, lang: str, start: date, end: date) -> str:
    """Brigade summary for brigadier — total for all members combined."""
    curr_sym = await _get_currency_symbol(info["director_id"])
    brigade_id = info.get("brigade_id")

    if not brigade_id:
        return t(lang, "reports.no_data")

    async with async_session() as session:
        result = await session.execute(select(Brigade).where(Brigade.id == brigade_id))
        brigade = result.scalar_one()

        result = await session.execute(
            select(BrigadeMember.worker_id).where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.is_active == True,
            )
        )
        worker_ids = [row[0] for row in result.all()]

        if not worker_ids:
            return t(lang, "reports.no_data")

        result = await session.execute(
            select(WorkEntry)
            .options(selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type))
            .where(
                WorkEntry.worker_id.in_(worker_ids),
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return t(lang, "reports.no_data")

    totals = {}
    grand_total = Decimal("0")
    for entry in entries:
        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            if tname not in totals:
                totals[tname] = {"unit": wt.unit, "quantity": Decimal("0"), "total": Decimal("0")}
            totals[tname]["quantity"] += item.quantity
            totals[tname]["total"] += item.total
            grand_total += item.total

    lines = [
        f"📊 {t(lang, 'reports.my_brigade')} — «{brigade.name}»",
        t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
        "",
    ]
    for tname, tdata in totals.items():
        ul = unit_label(tdata["unit"], lang)
        lines.append(f"  {tname}: {tdata['quantity']:.2f} {ul} = {tdata['total']:.2f} {curr_sym}")

    lines.append("")
    lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))
    return "\n".join(lines)


async def _build_my_brigade_by_project(info: dict, lang: str, start: date, end: date) -> str:
    """Brigade report by project for brigadier."""
    curr_sym = await _get_currency_symbol(info["director_id"])
    brigade_id = info.get("brigade_id")

    if not brigade_id:
        return t(lang, "reports.no_data")

    async with async_session() as session:
        result = await session.execute(
            select(BrigadeMember.worker_id).where(
                BrigadeMember.brigade_id == brigade_id,
                BrigadeMember.is_active == True,
            )
        )
        worker_ids = [row[0] for row in result.all()]

        if not worker_ids:
            return t(lang, "reports.no_data")

        result = await session.execute(
            select(WorkEntry)
            .options(
                selectinload(WorkEntry.items).selectinload(WorkEntryItem.work_type),
                selectinload(WorkEntry.worker),
                selectinload(WorkEntry.element).selectinload(Element.building).selectinload(Building.project),
            )
            .where(
                WorkEntry.worker_id.in_(worker_ids),
                WorkEntry.work_date >= start,
                WorkEntry.work_date <= end,
            )
        )
        entries = result.scalars().all()

    if not entries:
        return t(lang, "reports.no_data")

    # Group by project → worker → types
    projects = {}
    grand_total = Decimal("0")
    for entry in entries:
        proj_name = entry.element.building.project.name if entry.element and entry.element.building else "—"
        wname = entry.worker.name
        if proj_name not in projects:
            projects[proj_name] = {}
        if wname not in projects[proj_name]:
            projects[proj_name][wname] = {"types": {}, "total": Decimal("0")}
        for item in entry.items:
            wt = item.work_type
            tname = wt.get_name(lang)
            if tname not in projects[proj_name][wname]["types"]:
                projects[proj_name][wname]["types"][tname] = {"unit": wt.unit, "qty": Decimal("0"), "total": Decimal("0")}
            projects[proj_name][wname]["types"][tname]["qty"] += item.quantity
            projects[proj_name][wname]["types"][tname]["total"] += item.total
            projects[proj_name][wname]["total"] += item.total
            grand_total += item.total

    result2 = None
    async with async_session() as session:
        result2 = await session.execute(select(Brigade).where(Brigade.id == brigade_id))
        brigade = result2.scalar_one()

    lines = [
        f"📊 {t(lang, 'reports.my_brigade')} «{brigade.name}» — {t(lang, 'reports.by_project')}",
        t(lang, "reports.period", start=start.strftime("%d.%m.%y"), end=end.strftime("%d.%m.%y")),
        "",
    ]
    for pname, workers in projects.items():
        ptotal = sum(w["total"] for w in workers.values())
        lines.append(f"🏗️ {pname}: {ptotal:.2f} {curr_sym}")
        for wname, wdata in workers.items():
            lines.append(f"  👷 {wname}: {wdata['total']:.2f} {curr_sym}")
            for tname, tdata in wdata["types"].items():
                ul = unit_label(tdata["unit"], lang)
                lines.append(f"    {tname}: {tdata['qty']:.2f} {ul} = {tdata['total']:.2f} {curr_sym}")
        lines.append("")

    lines.append(t(lang, "reports.total_earned", total=f"{grand_total:.2f}", currency=curr_sym))
    return "\n".join(lines)


def get_reports_handlers():
    custom_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(report_custom_start, pattern=r"^rep:custom$")],
        states={
            REP_START_DATE: [
                CallbackQueryHandler(report_custom_cancel, pattern=r"^rep:back_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, report_start_date_entered),
            ],
            REP_END_DATE: [
                CallbackQueryHandler(report_custom_cancel, pattern=r"^rep:back_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, report_end_date_entered),
            ],
        },
        fallbacks=[CallbackQueryHandler(report_custom_cancel, pattern=r"^rep:back_menu$")],
        per_message=False,
    )

    return [
        custom_conv,
        CallbackQueryHandler(report_period_selected, pattern=r"^rep:(today|week|month)$"),
        CallbackQueryHandler(report_type_callback, pattern=r"^rept:(summary|brigade|project|personal|personal_projects|my_brigade|my_brigade_projects)$"),
        CallbackQueryHandler(export_excel, pattern=r"^rept:excel:"),
        CallbackQueryHandler(back_to_report_type, pattern=r"^rept:back_type$"),
    ]
