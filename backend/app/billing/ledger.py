"""Append-only ledger + FIFO payment allocation (DB side). Sign: + owes more, - paid/credit."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.allocation import allocate_fifo
from app.models.entities import Invoice, LedgerEntry, Payment, PaymentAllocation


async def balance(session: AsyncSession, lease_id: UUID) -> int:
    """Derived balance: >0 tenant owes, <0 tenant has credit."""
    total = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.lease_id == lease_id
        )
    )
    return int(total or 0)


async def post(
    session: AsyncSession,
    lease_id: UUID,
    entry_type: str,
    amount: int,
    ref_type: str,
    ref_id: UUID,
    description: str = "",
    created_by: UUID | None = None,
    reverses_id: int | None = None,
) -> LedgerEntry | None:
    if amount == 0:
        return None
    entry = LedgerEntry(
        lease_id=lease_id,
        entry_type=entry_type,
        amount=amount,
        ref_type=ref_type,
        ref_id=ref_id,
        description=description,
        created_by=created_by,
        reverses_id=reverses_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def allocate_credit(session: AsyncSession, lease_id: UUID) -> list[PaymentAllocation]:
    """Apply every payment's unallocated remainder to the oldest unpaid invoices first (FIFO).

    Called after a payment is recorded and after an invoice is issued, so overpayments become credit
    that is automatically applied to the next invoice. Caller must hold the lease row lock."""
    paid = (
        select(PaymentAllocation.payment_id, func.sum(PaymentAllocation.amount).label("used"))
        .group_by(PaymentAllocation.payment_id)
        .subquery()
    )
    pay_rows = (
        await session.execute(
            select(Payment.id, Payment.amount - func.coalesce(paid.c.used, 0))
            .outerjoin(paid, paid.c.payment_id == Payment.id)
            .where(Payment.lease_id == lease_id, Payment.reversed_at.is_(None))
            .order_by(Payment.paid_on, Payment.created_at)
        )
    ).all()
    payments = [(pid, int(rem)) for pid, rem in pay_rows if rem > 0]
    if not payments:
        return []
    covered = (
        select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount).label("covered"))
        .group_by(PaymentAllocation.invoice_id)
        .subquery()
    )
    inv_rows = (
        await session.execute(
            select(Invoice.id, Invoice.total - func.coalesce(covered.c.covered, 0))
            .outerjoin(covered, covered.c.invoice_id == Invoice.id)
            .where(Invoice.lease_id == lease_id, Invoice.status == "issued")
            .order_by(Invoice.period_start, Invoice.issue_date, Invoice.created_at)
        )
    ).all()
    invoices = [(iid, int(owed)) for iid, owed in inv_rows]
    created = [
        PaymentAllocation(payment_id=a.payment_id, invoice_id=a.invoice_id, amount=a.amount)
        for a in allocate_fifo(payments, invoices)
    ]
    session.add_all(created)
    await session.flush()
    return created
