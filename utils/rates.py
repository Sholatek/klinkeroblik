"""Rate resolution utility.

Priority:
1. BrigadeProjectRate — brigade + project specific
2. ProjectRate — project specific
3. BrigadeRate — brigade specific
4. WorkType.default_rate — global default
"""
from decimal import Decimal
from sqlalchemy import select
from database import async_session
from models import WorkType, ProjectRate, BrigadeRate, BrigadeProjectRate


async def get_effective_rate(
    work_type_id: int,
    project_id: int,
    brigade_id: int | None = None,
    *,
    session=None,
) -> Decimal:
    """Resolve effective rate for a work type given project and optional brigade."""

    async def _resolve(s):
        # 1. Brigade + project rate
        if brigade_id:
            result = await s.execute(
                select(BrigadeProjectRate.rate).where(
                    BrigadeProjectRate.brigade_id == brigade_id,
                    BrigadeProjectRate.project_id == project_id,
                    BrigadeProjectRate.work_type_id == work_type_id,
                )
            )
            rate = result.scalar_one_or_none()
            if rate is not None:
                return rate

        # 2. Project rate
        result = await s.execute(
            select(ProjectRate.rate).where(
                ProjectRate.project_id == project_id,
                ProjectRate.work_type_id == work_type_id,
            )
        )
        rate = result.scalar_one_or_none()
        if rate is not None:
            return rate

        # 3. Brigade rate
        if brigade_id:
            result = await s.execute(
                select(BrigadeRate.rate).where(
                    BrigadeRate.brigade_id == brigade_id,
                    BrigadeRate.work_type_id == work_type_id,
                )
            )
            rate = result.scalar_one_or_none()
            if rate is not None:
                return rate

        # 4. Default rate
        result = await s.execute(
            select(WorkType.default_rate).where(WorkType.id == work_type_id)
        )
        return result.scalar_one()

    if session:
        return await _resolve(session)
    else:
        async with async_session() as s:
            return await _resolve(s)


async def get_effective_rates_bulk(
    work_type_ids: list[int],
    project_id: int,
    brigade_id: int | None = None,
) -> dict[int, Decimal]:
    """Resolve effective rates for multiple work types at once."""
    rates = {}
    async with async_session() as session:
        for wt_id in work_type_ids:
            rates[wt_id] = await get_effective_rate(
                wt_id, project_id, brigade_id, session=session
            )
    return rates
