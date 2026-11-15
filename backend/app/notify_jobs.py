"""Scans that queue time-based notifications (idempotent via dedupe keys)."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.periods import next_billing_date
from app.models.entities import Invoice, Lease, PaymentAllocation, Unit
from app.services.notifications import enqueue

OVERDUE_EVERY_DAYS = 3  # throttle: one overdue reminder per invoice per 3 days
READING_REMINDER_DAYS_BEFORE = 2


async def scan_notifications(
    maker: async_sessionmaker[AsyncSession], today: date
) -> dict[str, int]:
    out = {"due_tomorrow": 0, "overdue": 0, "reading_reminder_upcoming": 0}
    async with maker() as s:
        covered = (
            select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount).label("c"))
            .group_by(PaymentAllocation.invoice_id)
            .subquery()
        )
        rows = (
            await s.execute(
                select(Invoice, Lease.tenant_id, Invoice.total - func.coalesce(covered.c.c, 0))
                .join(Lease, Lease.id == Invoice.lease_id)
                .outerjoin(covered, covered.c.invoice_id == Invoice.id)
                .where(
                    Invoice.status == "issued",
                    Lease.tenant_id.is_not(None),
                    Invoice.due_date <= today + timedelta(days=1),
                )
            )
        ).all()
        for inv, tenant_id, remaining in rows:
            if remaining <= 0 or tenant_id is None:
                continue
            payload = {
                "invoice_id": str(inv.id),
                "number": inv.number,
                "due_date": inv.due_date.isoformat(),
                "remaining": int(remaining),
            }
            if inv.due_date == today + timedelta(days=1):
                out["due_tomorrow"] += await enqueue(
                    s, tenant_id, "due_tomorrow", f"due_tomorrow:{inv.id}", payload
                )
            elif inv.due_date < today:
                days = (today - inv.due_date).days
                bucket = days // OVERDUE_EVERY_DAYS
                out["overdue"] += await enqueue(
                    s, tenant_id, "overdue", f"overdue:{inv.id}:{bucket}", {**payload, "days": days}
                )
        leases = (
            await s.execute(
                select(Lease, Unit.name)
                .join(Unit, Unit.id == Lease.unit_id)
                .where(
                    Lease.status == "active",
                    Lease.tenant_id.is_not(None),
                    Lease.start_date <= today,
                )
            )
        ).all()
        for lease, unit_name in leases:
            nxt = next_billing_date(today, lease.billing_day)
            in_window = nxt - today == timedelta(days=READING_REMINDER_DAYS_BEFORE)
            if in_window and lease.tenant_id and (lease.end_date is None or lease.end_date >= nxt):
                out["reading_reminder_upcoming"] += await enqueue(
                    s,
                    lease.tenant_id,
                    "reading_reminder_upcoming",
                    f"reading_reminder_upcoming:{lease.id}:{nxt}",
                    {"unit": unit_name},
                )
        await s.commit()
    return out
