"""Reading validation rules shared by submit / confirm / baseline."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Unprocessable
from app.models.entities import Lease, MeterReading

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def tenant_prefix(tenant_id: UUID) -> str:
    return f"tenants/{tenant_id}/readings/"


async def check_monotonic(
    session: AsyncSession,
    meter_id: UUID,
    value: Decimal,
    reading_date: date,
    exclude_id: UUID | None = None,
) -> None:
    """A reading may not be lower than the previous confirmed one (unless it is a new baseline),
    nor higher than a later confirmed one on the same meter."""
    base = select(MeterReading).where(
        MeterReading.meter_id == meter_id, MeterReading.status == "confirmed"
    )
    if exclude_id:
        base = base.where(MeterReading.id != exclude_id)
    prev = (
        await session.execute(
            base.where(MeterReading.reading_date <= reading_date)
            .order_by(MeterReading.reading_date.desc(), MeterReading.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prev is not None and value < prev.value:
        raise Unprocessable(
            f"Reading {value} is lower than the previous confirmed reading {prev.value}. "
            "If the meter was replaced, ask the owner to record a new baseline.",
            code="reading_lower_than_previous",
        )
    nxt = (
        await session.execute(
            base.where(MeterReading.reading_date > reading_date)
            .order_by(MeterReading.reading_date.asc(), MeterReading.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if nxt is not None and not nxt.is_baseline and value > nxt.value:
        raise Unprocessable(
            f"Reading {value} is higher than a later confirmed reading {nxt.value}",
            code="reading_higher_than_next",
        )


async def lease_on_date(session: AsyncSession, unit_id: UUID, on: date) -> Lease | None:
    return (
        await session.execute(
            select(Lease).where(
                Lease.unit_id == unit_id,
                Lease.status != "cancelled",
                Lease.start_date <= on,
                (Lease.end_date.is_(None)) | (Lease.end_date >= on),
            )
        )
    ).scalar_one_or_none()
