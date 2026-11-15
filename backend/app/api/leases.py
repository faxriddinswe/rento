from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentActor, Session, authorize
from app.config import get_settings
from app.domain.policies import Action, Resource, can
from app.errors import Conflict, Unprocessable
from app.models.entities import Invite, Lease, Property, Unit
from app.schemas import InviteIn, InviteOut, LeaseEndIn, LeaseIn, LeaseOut
from app.services.access import get_lease, get_unit
from app.services.audit import audit
from app.services.auth import INVITE_MAX_AGE, sign_invite

router = APIRouter(tags=["leases"])


def _snapshot(lease: Lease) -> dict[str, object]:
    return {
        "unit_id": str(lease.unit_id),
        "tenant_id": str(lease.tenant_id) if lease.tenant_id else None,
        "start_date": lease.start_date.isoformat(),
        "end_date": lease.end_date.isoformat() if lease.end_date else None,
        "monthly_rent": lease.monthly_rent,
        "billing_day": lease.billing_day,
        "status": lease.status,
    }


@router.post("/units/{unit_id}/leases", response_model=LeaseOut, status_code=201)
async def create_lease(
    unit_id: UUID, body: LeaseIn, session: Session, actor: CurrentActor
) -> Lease:
    unit, _, res = await get_unit(session, unit_id)
    authorize(actor, Action.LEASE_MANAGE, res)
    lease = Lease(unit_id=unit.id, **body.model_dump())
    session.add(lease)
    try:
        await session.flush()
    except IntegrityError as exc:
        if "ex_leases_no_overlap" in str(exc):
            raise Conflict(
                "This unit already has a lease overlapping these dates", code="lease_overlap"
            ) from exc
        raise
    await audit(session, actor.id, "lease.create", "lease", lease.id, after=_snapshot(lease))
    return lease


@router.get("/leases", response_model=list[LeaseOut])
async def list_leases(
    session: Session, actor: CurrentActor, unit_id: UUID | None = None, status: str | None = None
) -> list[Lease]:
    stmt = (
        select(Lease, Property)
        .join(Unit, Unit.id == Lease.unit_id)
        .join(Property, Property.id == Unit.property_id)
        .order_by(Lease.start_date.desc())
    )
    if unit_id:
        stmt = stmt.where(Lease.unit_id == unit_id)
    if status:
        stmt = stmt.where(Lease.status == status)
    if actor.role == "owner":
        stmt = stmt.where(Property.owner_id == actor.id)
    elif actor.role == "manager":
        stmt = stmt.where(Property.id.in_(list(actor.managed)))
    else:
        stmt = stmt.where(Lease.tenant_id == actor.id)
    rows = (await session.execute(stmt)).all()
    return [
        lease
        for lease, prop in rows
        if can(actor, Action.LEASE_READ, Resource(prop.owner_id, prop.id, lease.tenant_id))
    ]


@router.get("/leases/{lease_id}", response_model=LeaseOut)
async def read_lease(lease_id: UUID, session: Session, actor: CurrentActor) -> Lease:
    lease, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.LEASE_READ, res)
    return lease


@router.post("/leases/{lease_id}/end", response_model=LeaseOut)
async def end_lease(
    lease_id: UUID, body: LeaseEndIn, session: Session, actor: CurrentActor
) -> Lease:
    lease, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.LEASE_MANAGE, res)
    if lease.status != "active":
        raise Conflict("Lease is not active", code="lease_not_active")
    if body.end_date < lease.start_date:
        raise Unprocessable("end_date before start_date")
    before = _snapshot(lease)
    lease.end_date, lease.status = body.end_date, "ended"
    await session.flush()
    await audit(session, actor.id, "lease.end", "lease", lease.id, before, _snapshot(lease))
    return lease


@router.post("/leases/{lease_id}/invite", response_model=InviteOut, status_code=201)
async def invite_tenant(
    lease_id: UUID, body: InviteIn, session: Session, actor: CurrentActor
) -> InviteOut:
    lease, _, res = await get_lease(session, lease_id)
    authorize(actor, Action.LEASE_MANAGE, res)
    if lease.tenant_id is not None:
        raise Conflict("Lease already has a tenant", code="tenant_assigned")
    expires = datetime.now(UTC) + timedelta(seconds=INVITE_MAX_AGE)
    invite = Invite(
        lease_id=lease.id, email=body.email.lower(), full_name=body.full_name, expires_at=expires
    )
    session.add(invite)
    await session.flush()
    token = sign_invite(invite.id)
    await audit(
        session, actor.id, "invite.create", "lease", lease.id, after={"email": invite.email}
    )
    url = f"{get_settings().app_base_url}/invite/{token}"
    return InviteOut(invite_id=invite.id, token=token, url=url, expires_at=expires)
