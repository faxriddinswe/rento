"""DB side of billing: gather facts -> pure core -> persist invoice, ledger entry, allocations.

Idempotent: UNIQUE(lease_id, period_start) + a row lock on the lease make re-runs a no-op."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import core
from app.billing.ledger import allocate_credit, balance, post
from app.models.entities import (
    Invoice,
    InvoiceLine,
    Lease,
    LeaseAdjustment,
    Meter,
    MeterReading,
    Property,
    Tariff,
    Unit,
)
from app.services.audit import audit
from app.services.notifications import enqueue

Outcome = Literal["created", "exists", "skipped", "missing_tariff"]


@dataclass
class BillingResult:
    outcome: Outcome
    invoice: Invoice | None = None
    detail: str = ""


def _tariffs(rows: list[Tariff]) -> tuple[core.TariffIn, ...]:
    out = []
    for t in rows:
        tiers = None
        if t.tiers:
            tiers = tuple(
                core.TierIn(
                    None if x["up_to"] is None else Decimal(x["up_to"]), Decimal(x["price"])
                )
                for x in t.tiers
            )
        out.append(core.TariffIn(t.effective_from, t.effective_to, t.unit_price, tiers))
    return tuple(out)


async def _meter_inputs(
    session: AsyncSession, lease: Lease, prop: Property, cutoff: date
) -> tuple[core.MeterIn, ...]:
    meters = (
        (
            await session.execute(
                select(Meter).where(Meter.unit_id == lease.unit_id, Meter.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    tariffs = (
        (await session.execute(select(Tariff).where(Tariff.property_id == prop.id))).scalars().all()
    )
    # last billed reading / pending marker per meter, from this lease's issued invoices
    billed = (
        await session.execute(
            select(InvoiceLine, Invoice.period_start, MeterReading.reading_date)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .outerjoin(MeterReading, MeterReading.id == InvoiceLine.reading_to_id)
            .where(
                Invoice.lease_id == lease.id,
                Invoice.status == "issued",
                InvoiceLine.meter_id.is_not(None),
            )
            .order_by(Invoice.period_start.desc(), InvoiceLine.sort.desc())
        )
    ).all()
    last_billed: dict[UUID, UUID] = {}
    last_billed_date: dict[UUID, date] = {}
    prior_pending: dict[UUID, bool] = {}
    for line, _, rdate in billed:
        assert line.meter_id is not None
        prior_pending.setdefault(line.meter_id, line.pending_reading)
        if (
            line.reading_to_id
            and rdate
            and (line.meter_id not in last_billed_date or rdate > last_billed_date[line.meter_id])
        ):
            last_billed[line.meter_id] = line.reading_to_id
            last_billed_date[line.meter_id] = rdate
    out = []
    for m in meters:
        readings = (
            (
                await session.execute(
                    select(MeterReading).where(
                        MeterReading.meter_id == m.id,
                        MeterReading.status == "confirmed",
                        MeterReading.reading_date >= lease.start_date,
                        MeterReading.reading_date <= cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        out.append(
            core.MeterIn(
                id=m.id,
                kind=m.kind,
                label=m.serial or m.kind,
                readings=tuple(
                    core.ReadingIn(
                        r.id, r.reading_date, r.value, r.is_baseline, r.replaced_final_value
                    )
                    for r in readings
                ),
                tariffs=_tariffs([t for t in tariffs if t.kind == m.kind]),
                last_billed_reading_id=last_billed.get(m.id),
                prior_pending=prior_pending.get(m.id, False),
            )
        )
    return tuple(out)


async def create_invoice(
    session: AsyncSession,
    lease_id: UUID,
    period_start: date,
    *,
    is_final: bool = False,
    actor_id: UUID | None = None,
) -> BillingResult:
    """Create the invoice for ``period_start`` once. Safe to call repeatedly / concurrently."""
    lease = (
        await session.execute(select(Lease).where(Lease.id == lease_id).with_for_update())
    ).scalar_one()
    existing = await session.scalar(
        select(Invoice).where(Invoice.lease_id == lease.id, Invoice.period_start == period_start)
    )
    if existing is not None:
        return BillingResult("exists", existing)
    unit = await session.get(Unit, lease.unit_id)
    assert unit is not None
    prop = await session.get(Property, unit.property_id)
    assert prop is not None
    has_prior = await session.scalar(
        select(Invoice.id).where(Invoice.lease_id == lease.id).limit(1)
    )
    adjustments = (
        (
            await session.execute(
                select(LeaseAdjustment)
                .where(LeaseAdjustment.lease_id == lease.id, LeaseAdjustment.invoice_id.is_(None))
                .order_by(LeaseAdjustment.created_at)
            )
        )
        .scalars()
        .all()
    )
    cutoff = lease.end_date + timedelta(days=1) if is_final and lease.end_date else period_start
    req = core.InvoiceRequest(
        lease=core.LeaseIn(
            lease.start_date, lease.end_date, lease.monthly_rent, lease.billing_day, lease.due_days
        ),
        period_start=period_start,
        meters=await _meter_inputs(session, lease, prop, cutoff),
        adjustments=tuple(core.AdjustmentIn(a.id, a.amount, a.description) for a in adjustments),
        is_first=has_prior is None and not is_final,
        is_final=is_final,
    )
    try:
        draft = core.build_invoice(req)
    except core.MissingTariff as exc:
        await enqueue(
            session,
            prop.owner_id,
            "billing_failed",
            f"billing_failed:{lease.id}:{period_start}:{exc.kind}",
            {
                "lease_id": str(lease.id),
                "period_start": period_start.isoformat(),
                "reason": f"No {exc.kind} tariff effective on {exc.on}",
            },
        )
        return BillingResult("missing_tariff", None, str(exc))
    if draft is None:
        return BillingResult("skipped")

    number = f"INV-{await session.scalar(text("SELECT nextval('invoice_number_seq')")):06d}"
    prev_balance = await balance(session, lease.id)
    invoice = Invoice(
        lease_id=lease.id,
        number=number,
        period_start=draft.period_start,
        period_end=draft.period_end,
        issue_date=draft.issue_date,
        due_date=draft.due_date,
        total=draft.total,
        previous_balance=prev_balance,
    )
    session.add(invoice)
    await session.flush()
    for i, ln in enumerate(draft.lines):
        session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                sort=i,
                kind=ln.kind,
                description=ln.description,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=ln.amount,
                meter_id=ln.meter_id,
                reading_from_id=ln.reading_from_id,
                reading_to_id=ln.reading_to_id,
                pending_reading=ln.pending_reading,
            )
        )
    for a in adjustments:
        a.invoice_id = invoice.id
    await session.flush()
    await post(
        session,
        lease.id,
        "invoice",
        invoice.total,
        "invoice",
        invoice.id,
        f"Invoice {number}",
        actor_id,
    )
    await allocate_credit(session, lease.id)  # existing credit pays the new invoice automatically
    await audit(
        session,
        actor_id,
        "invoice.create",
        "invoice",
        invoice.id,
        None,
        {
            "number": number,
            "lease_id": str(lease.id),
            "period_start": period_start.isoformat(),
            "total": invoice.total,
            "lines": len(draft.lines),
        },
    )
    if lease.tenant_id:
        await enqueue(
            session,
            lease.tenant_id,
            "invoice_issued",
            f"invoice_issued:{invoice.id}",
            {
                "invoice_id": str(invoice.id),
                "number": number,
                "total": invoice.total,
                "due_date": invoice.due_date.isoformat(),
            },
        )
    for ln in draft.lines:
        if ln.pending_reading and ln.meter_id:
            await enqueue(
                session,
                prop.owner_id,
                "reading_pending",
                f"reading_pending:{invoice.id}:{ln.meter_id}",
                {"invoice_id": str(invoice.id), "meter_id": str(ln.meter_id), "unit": unit.name},
            )
            if lease.tenant_id:
                await enqueue(
                    session,
                    lease.tenant_id,
                    "reading_reminder",
                    f"reading_reminder:{invoice.id}:{ln.meter_id}",
                    {"meter_id": str(ln.meter_id), "unit": unit.name},
                )
    return BillingResult("created", invoice)
