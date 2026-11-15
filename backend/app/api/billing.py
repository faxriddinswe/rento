from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentActor, Session, authorize
from app.billing.job import BillingSummary
from app.billing.periods import period_starts_between
from app.billing.service import create_invoice
from app.domain.policies import Action
from app.errors import Conflict
from app.models.entities import Invoice, InvoiceLine, LeaseAdjustment, PaymentAllocation
from app.schemas import (
    AdjustmentIn,
    AdjustmentOut,
    BillingRunIn,
    BillingRunOut,
    InvoiceLineOut,
    InvoiceOut,
)
from app.services.access import get_lease
from app.services.audit import audit
from app.services.clock import today_local

router = APIRouter(tags=["billing"])


async def invoice_out(session: Session, inv: Invoice, with_lines: bool = True) -> InvoiceOut:
    paid = int(
        await session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.invoice_id == inv.id
            )
        )
        or 0
    )
    lines = []
    if with_lines:
        rows = await session.scalars(
            select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.sort)
        )
        lines = [InvoiceLineOut.model_validate(r) for r in rows]
    return InvoiceOut(
        id=inv.id,
        lease_id=inv.lease_id,
        number=inv.number,
        period_start=inv.period_start,
        period_end=inv.period_end,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        total=inv.total,
        previous_balance=inv.previous_balance,
        status=inv.status,
        paid=paid,
        remaining=max(inv.total - paid, 0) if inv.status == "issued" else 0,
        lines=lines,
    )


@router.get("/leases/{lease_id}/invoices", response_model=list[InvoiceOut])
async def list_invoices(lease_id: UUID, session: Session, actor: CurrentActor) -> list[InvoiceOut]:
    _, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.INVOICE_READ, res)
    rows = (
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.lease_id == lease_id)
                .order_by(Invoice.period_start.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await invoice_out(session, i) for i in rows]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def read_invoice(invoice_id: UUID, session: Session, actor: CurrentActor) -> InvoiceOut:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        from app.errors import NotFound

        raise NotFound("Invoice not found")
    _, _, res = await get_lease(session, inv.lease_id)
    authorize(actor, Action.INVOICE_READ, res)
    return await invoice_out(session, inv)


@router.post("/leases/{lease_id}/billing/run", response_model=BillingRunOut)
async def run_billing_for_lease(
    lease_id: UUID, body: BillingRunIn, session: Session, actor: CurrentActor
) -> BillingRunOut:
    """Owner: (re)run billing for one lease up to a date. Idempotent — existing periods are kept.
    Used to back-fill leases created in the past; periods are billed oldest first."""
    lease, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.BILLING_RUN, res)
    through = body.through or today_local()
    summary = BillingSummary()
    for ps in period_starts_between(
        lease.start_date, lease.end_date, lease.billing_day, lease.start_date, through
    ):
        r = await create_invoice(session, lease.id, ps, actor_id=actor.id)
        setattr(summary, r.outcome, getattr(summary, r.outcome) + 1)
        if r.outcome == "created" and r.invoice:
            summary.invoices.append(r.invoice.id)
    await audit(
        session,
        actor.id,
        "billing.run",
        "lease",
        lease.id,
        None,
        {"through": through.isoformat(), "created": summary.created},
    )
    return BillingRunOut(
        created=summary.created,
        exists=summary.exists,
        skipped=summary.skipped,
        missing_tariff=summary.missing_tariff,
        invoice_ids=summary.invoices,
    )


@router.post("/leases/{lease_id}/adjustments", response_model=AdjustmentOut, status_code=201)
async def add_adjustment(
    lease_id: UUID, body: AdjustmentIn, session: Session, actor: CurrentActor
) -> LeaseAdjustment:
    """Queue a manual charge/discount; it appears as a line on the lease's NEXT invoice
    (issued invoices are never edited)."""
    lease, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.LEASE_MANAGE, res)
    if lease.status == "cancelled":
        raise Conflict("Lease is cancelled", code="lease_cancelled")
    adj = LeaseAdjustment(
        lease_id=lease.id, amount=body.amount, description=body.description, created_by=actor.id
    )
    session.add(adj)
    await session.flush()
    await audit(
        session,
        actor.id,
        "adjustment.create",
        "lease",
        lease.id,
        None,
        {"amount": body.amount, "description": body.description},
    )
    return adj
