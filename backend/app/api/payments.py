from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.billing import invoice_out
from app.api.deps import CurrentActor, Session, authorize
from app.billing.ledger import allocate_credit, balance, post
from app.domain.policies import Action
from app.errors import Conflict, NotFound, Unprocessable
from app.models.entities import Invoice, Lease, LedgerEntry, Payment, PaymentAllocation
from app.schemas import (
    BalanceOut,
    InvoiceOut,
    LedgerEntryOut,
    PaymentIn,
    PaymentOut,
    ReasonIn,
)
from app.services.access import get_lease
from app.services.audit import audit
from app.services.clock import today_local
from app.services.notifications import enqueue

router = APIRouter(tags=["payments", "ledger"])


async def _lock(session: Session, lease_id: UUID) -> None:
    await session.execute(select(Lease.id).where(Lease.id == lease_id).with_for_update())


async def _payment_out(session: Session, p: Payment) -> PaymentOut:
    allocated = int(
        await session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.payment_id == p.id
            )
        )
        or 0
    )
    out = PaymentOut.model_validate(p)
    out.allocated = allocated
    out.credit = 0 if p.reversed_at else p.amount - allocated
    return out


@router.post("/leases/{lease_id}/payments", response_model=PaymentOut, status_code=201)
async def record_payment(
    lease_id: UUID, body: PaymentIn, session: Session, actor: CurrentActor
) -> PaymentOut:
    lease, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.PAYMENT_RECORD, res)
    if body.paid_on > today_local():
        raise Unprocessable("Payment date is in the future", code="payment_future")
    await _lock(session, lease.id)
    payment = Payment(
        lease_id=lease.id,
        amount=body.amount,
        paid_on=body.paid_on,
        method=body.method,
        reference=body.reference,
        note=body.note,
        recorded_by=actor.id,
    )
    session.add(payment)
    await session.flush()
    await post(
        session,
        lease.id,
        "payment",
        -body.amount,
        "payment",
        payment.id,
        f"Payment ({body.method})",
        actor.id,
    )
    await allocate_credit(session, lease.id)
    await audit(
        session,
        actor.id,
        "payment.record",
        "payment",
        payment.id,
        None,
        {
            "lease_id": str(lease.id),
            "amount": body.amount,
            "paid_on": body.paid_on.isoformat(),
            "method": body.method,
        },
    )
    if lease.tenant_id:
        await enqueue(
            session,
            lease.tenant_id,
            "payment_received",
            f"payment_received:{payment.id}",
            {"payment_id": str(payment.id), "amount": body.amount},
        )
    return await _payment_out(session, payment)


@router.get("/leases/{lease_id}/payments", response_model=list[PaymentOut])
async def list_payments(lease_id: UUID, session: Session, actor: CurrentActor) -> list[PaymentOut]:
    _, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.PAYMENT_READ, res)
    rows = (
        (
            await session.execute(
                select(Payment)
                .where(Payment.lease_id == lease_id)
                .order_by(Payment.paid_on.desc(), Payment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _payment_out(session, p) for p in rows]


@router.post("/payments/{payment_id}/reverse", response_model=PaymentOut)
async def reverse_payment(
    payment_id: UUID, body: ReasonIn, session: Session, actor: CurrentActor
) -> PaymentOut:
    """Owner only. Appends reversing ledger entry and negative allocations; the payment row is kept."""
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise NotFound("Payment not found")
    lease, _, res = await get_lease(session, payment.lease_id)
    authorize(actor, Action.PAYMENT_REVERSE, res)
    await _lock(session, lease.id)
    await session.refresh(payment)
    if payment.reversed_at is not None:
        raise Conflict("Payment already reversed", code="already_reversed")
    original = await session.scalar(
        select(LedgerEntry.id).where(
            LedgerEntry.ref_type == "payment",
            LedgerEntry.ref_id == payment.id,
            LedgerEntry.entry_type == "payment",
        )
    )
    allocs = (
        await session.execute(
            select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount))
            .where(PaymentAllocation.payment_id == payment.id)
            .group_by(PaymentAllocation.invoice_id)
        )
    ).all()
    for invoice_id, amount in allocs:
        if amount:
            session.add(
                PaymentAllocation(payment_id=payment.id, invoice_id=invoice_id, amount=-int(amount))
            )
    payment.reversed_at = datetime.now(UTC)
    await session.flush()
    await post(
        session,
        lease.id,
        "payment_reversal",
        payment.amount,
        "payment",
        payment.id,
        f"Reversal: {body.reason}",
        actor.id,
        reverses_id=original,
    )
    await allocate_credit(session, lease.id)  # other payments' credit may now cover freed invoices
    await audit(
        session,
        actor.id,
        "payment.reverse",
        "payment",
        payment.id,
        {"amount": payment.amount},
        {"reversed": True, "reason": body.reason},
    )
    return await _payment_out(session, payment)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
async def void_invoice(
    invoice_id: UUID, body: ReasonIn, session: Session, actor: CurrentActor
) -> InvoiceOut:
    """Owner only. Voids an issued invoice via a reversing ledger entry; payments that were
    allocated to it become credit again and are re-applied FIFO to other invoices."""
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("Invoice not found")
    lease, _, res = await get_lease(session, inv.lease_id)
    authorize(actor, Action.PAYMENT_REVERSE, res)
    await _lock(session, lease.id)
    await session.refresh(inv)
    if inv.status != "issued":
        raise Conflict("Invoice is already void", code="already_void")
    allocs = (
        await session.execute(
            select(PaymentAllocation.payment_id, func.sum(PaymentAllocation.amount))
            .where(PaymentAllocation.invoice_id == inv.id)
            .group_by(PaymentAllocation.payment_id)
        )
    ).all()
    for payment_id, amount in allocs:
        if amount:
            session.add(
                PaymentAllocation(payment_id=payment_id, invoice_id=inv.id, amount=-int(amount))
            )
    inv.status = "void"
    await session.flush()
    original = await session.scalar(
        select(LedgerEntry.id).where(
            LedgerEntry.ref_type == "invoice",
            LedgerEntry.ref_id == inv.id,
            LedgerEntry.entry_type == "invoice",
        )
    )
    await post(
        session,
        lease.id,
        "invoice_void",
        -inv.total,
        "invoice",
        inv.id,
        f"Void {inv.number}: {body.reason}",
        actor.id,
        reverses_id=original,
    )
    await allocate_credit(session, lease.id)
    await audit(
        session,
        actor.id,
        "invoice.void",
        "invoice",
        inv.id,
        {"status": "issued", "total": inv.total},
        {"status": "void", "reason": body.reason},
    )
    return await invoice_out(session, inv)


@router.get("/leases/{lease_id}/ledger", response_model=list[LedgerEntryOut])
async def read_ledger(
    lease_id: UUID, session: Session, actor: CurrentActor
) -> list[LedgerEntryOut]:
    _, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.LEDGER_READ, res)
    rows = (
        (
            await session.execute(
                select(LedgerEntry).where(LedgerEntry.lease_id == lease_id).order_by(LedgerEntry.id)
            )
        )
        .scalars()
        .all()
    )
    running, out = 0, []
    for e in rows:
        running += e.amount
        item = LedgerEntryOut.model_validate(e)
        item.running_balance = running
        out.append(item)
    return out


@router.get("/leases/{lease_id}/balance", response_model=BalanceOut)
async def read_balance(lease_id: UUID, session: Session, actor: CurrentActor) -> BalanceOut:
    _, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.LEDGER_READ, res)
    return await balance_summary(session, lease_id)


async def balance_summary(session: Session, lease_id: UUID) -> BalanceOut:
    bal = await balance(session, lease_id)
    covered = (
        select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount).label("c"))
        .group_by(PaymentAllocation.invoice_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Invoice.due_date, Invoice.total - func.coalesce(covered.c.c, 0))
            .outerjoin(covered, covered.c.invoice_id == Invoice.id)
            .where(Invoice.lease_id == lease_id, Invoice.status == "issued")
            .order_by(Invoice.due_date)
        )
    ).all()
    today = today_local()
    open_rows = [(d, int(r)) for d, r in rows if r > 0]
    overdue = sum(r for d, r in open_rows if d < today)
    nxt = next(((d, r) for d, r in open_rows if d >= today), None)
    return BalanceOut(
        lease_id=lease_id,
        balance=bal,
        owed=max(bal, 0),
        credit=max(-bal, 0),
        overdue=overdue,
        next_due_date=nxt[0] if nxt else None,
        next_due_amount=nxt[1] if nxt else 0,
    )
