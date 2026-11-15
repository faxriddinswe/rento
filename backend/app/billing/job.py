"""Daily billing job: for every lease with a period starting in the catch-up window, create the
invoice exactly once. Each lease runs in its own transaction so one failure never blocks the rest."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.periods import period_starts_between
from app.billing.service import create_invoice
from app.logging import get_logger
from app.models.entities import Lease

CATCH_UP_DAYS = 7  # tolerate a few days of worker downtime; older gaps via the manual endpoint


@dataclass
class BillingSummary:
    created: int = 0
    exists: int = 0
    skipped: int = 0
    missing_tariff: int = 0
    failed: int = 0
    invoices: list[UUID] = field(default_factory=list)


async def run_billing(
    maker: async_sessionmaker[AsyncSession], today: date, catch_up_days: int = CATCH_UP_DAYS
) -> BillingSummary:
    log = get_logger("billing")
    summary = BillingSummary()
    window_start = today - timedelta(days=catch_up_days - 1)
    async with maker() as s:
        lease_ids = (
            (
                await s.execute(
                    select(Lease.id).where(
                        Lease.status.in_(("active", "ended")),
                        Lease.start_date <= today,
                        or_(
                            Lease.end_date.is_(None),
                            Lease.end_date >= window_start - timedelta(days=1),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
    for lease_id in lease_ids:
        async with maker() as s:
            try:
                lease = await s.get(Lease, lease_id)
                assert lease is not None
                todo: list[tuple[date, bool]] = [
                    (d, False)
                    for d in period_starts_between(
                        lease.start_date, lease.end_date, lease.billing_day, window_start, today
                    )
                ]
                if lease.end_date is not None:
                    final_day = lease.end_date + timedelta(days=1)
                    if window_start <= final_day <= today:
                        todo.append((final_day, True))
                for period_start, is_final in todo:
                    res = await create_invoice(s, lease_id, period_start, is_final=is_final)
                    setattr(summary, res.outcome, getattr(summary, res.outcome) + 1)
                    if res.outcome == "created" and res.invoice:
                        summary.invoices.append(res.invoice.id)
                await s.commit()
            except Exception as exc:
                await s.rollback()
                summary.failed += 1
                log.error("billing_failed", lease_id=str(lease_id), error=repr(exc), exc_info=True)
    log.info(
        "billing_done",
        today=today.isoformat(),
        created=summary.created,
        exists=summary.exists,
        skipped=summary.skipped,
        missing_tariff=summary.missing_tariff,
        failed=summary.failed,
    )
    return summary
