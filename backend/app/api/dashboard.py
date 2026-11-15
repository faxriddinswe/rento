from datetime import date
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentActor, Session, authorize
from app.domain.policies import Action, Resource, can
from app.errors import Forbidden
from app.models.entities import (
    AuditLog,
    Invoice,
    Lease,
    Meter,
    MeterReading,
    Payment,
    PaymentAllocation,
    Property,
    Unit,
    User,
)
from app.schemas import AuditOut, DashboardOut, OverdueRow
from app.services.clock import today_local

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(session: Session, actor: CurrentActor) -> DashboardOut:
    if actor.role == "tenant":
        raise Forbidden("Owner/manager only")
    today = today_local()
    month_start = today.replace(day=1)
    next_month = date(month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1)
    props = (await session.execute(select(Property))).scalars().all()
    allowed = {p.id for p in props if can(actor, Action.DASHBOARD_READ, Resource(p.owner_id, p.id))}
    if not allowed:
        return DashboardOut(
            month=month_start.strftime("%Y-%m"),
            expected=0,
            collected=0,
            outstanding=0,
            active_leases=0,
            pending_readings=0,
            overdue=[],
        )
    lease_scope = (
        select(Lease.id).join(Unit, Unit.id == Lease.unit_id).where(Unit.property_id.in_(allowed))
    )
    expected = await session.scalar(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.lease_id.in_(lease_scope),
            Invoice.status == "issued",
            Invoice.issue_date >= month_start,
            Invoice.issue_date < next_month,
        )
    )
    collected = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.lease_id.in_(lease_scope),
            Payment.reversed_at.is_(None),
            Payment.paid_on >= month_start,
            Payment.paid_on < next_month,
        )
    )
    covered = (
        select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount).label("c"))
        .group_by(PaymentAllocation.invoice_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Invoice.lease_id, Invoice.due_date, Invoice.total - func.coalesce(covered.c.c, 0)
            )
            .outerjoin(covered, covered.c.invoice_id == Invoice.id)
            .where(Invoice.lease_id.in_(lease_scope), Invoice.status == "issued")
        )
    ).all()
    outstanding = sum(int(r) for _, _, r in rows if r > 0)
    per_lease: dict[UUID, tuple[int, date]] = {}
    for lease_id, due, rem in rows:
        if rem > 0 and due < today:
            amt, oldest = per_lease.get(lease_id, (0, due))
            per_lease[lease_id] = (amt + int(rem), min(oldest, due))
    overdue: list[OverdueRow] = []
    for lease_id, (amt, oldest) in per_lease.items():
        lease = await session.get(Lease, lease_id)
        assert lease is not None
        unit = await session.get(Unit, lease.unit_id)
        assert unit is not None
        prop = await session.get(Property, unit.property_id)
        assert prop is not None
        tenant = await session.get(User, lease.tenant_id) if lease.tenant_id else None
        overdue.append(
            OverdueRow(
                lease_id=lease_id,
                property_name=prop.name,
                unit_name=unit.name,
                tenant_name=tenant.full_name if tenant else None,
                overdue=amt,
                oldest_due_date=oldest,
            )
        )
    overdue.sort(key=lambda r: r.oldest_due_date)
    active = await session.scalar(
        select(func.count())
        .select_from(Lease)
        .where(Lease.id.in_(lease_scope), Lease.status == "active")
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(MeterReading)
        .join(Meter, Meter.id == MeterReading.meter_id)
        .join(Unit, Unit.id == Meter.unit_id)
        .where(Unit.property_id.in_(allowed), MeterReading.status == "pending")
    )
    return DashboardOut(
        month=month_start.strftime("%Y-%m"),
        expected=int(expected or 0),
        collected=int(collected or 0),
        outstanding=outstanding,
        active_leases=int(active or 0),
        pending_readings=int(pending or 0),
        overdue=overdue,
    )


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    session: Session,
    actor: CurrentActor,
    entity_type: str | None = None,
    action: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Owner only: audit rows about the owner's own data (scoped by owner_id)."""
    authorize(actor, Action.AUDIT_READ, Resource(owner_id=actor.id))
    stmt = (
        select(AuditLog)
        .where(AuditLog.owner_id == actor.id)
        .order_by(AuditLog.id.desc())
        .limit(min(limit, 500))
        .offset(offset)
    )
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list((await session.execute(stmt)).scalars())
