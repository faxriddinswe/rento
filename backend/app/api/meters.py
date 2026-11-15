from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentActor, Session, authorize
from app.domain.policies import Action, Resource
from app.errors import Conflict
from app.models.entities import Meter, Tariff
from app.schemas import MeterIn, MeterOut, MeterPatch, TariffIn, TariffOut
from app.services.access import (
    active_tenant_lease_for_unit,
    get_meter,
    get_property,
    get_unit,
    property_resource,
)
from app.services.audit import audit

router = APIRouter(tags=["meters", "tariffs"])


@router.post("/units/{unit_id}/meters", response_model=MeterOut, status_code=201)
async def create_meter(
    unit_id: UUID, body: MeterIn, session: Session, actor: CurrentActor
) -> Meter:
    unit, _, res = await get_unit(session, unit_id)
    authorize(actor, Action.METER_MANAGE, res)
    meter = Meter(unit_id=unit.id, **body.model_dump())
    session.add(meter)
    await session.flush()
    await audit(session, actor.id, "meter.create", "meter", meter.id, after=body.model_dump())
    return meter


@router.get("/units/{unit_id}/meters", response_model=list[MeterOut])
async def list_meters(unit_id: UUID, session: Session, actor: CurrentActor) -> list[Meter]:
    unit, prop, _ = await get_unit(session, unit_id)
    tenant_id = None
    if actor.role == "tenant":
        lease = await active_tenant_lease_for_unit(session, unit.id, actor.id)
        tenant_id = lease.tenant_id if lease else None
    authorize(actor, Action.METER_READ, Resource(prop.owner_id, prop.id, tenant_id))
    return list(
        (
            await session.execute(
                select(Meter).where(Meter.unit_id == unit_id).order_by(Meter.kind)
            )
        ).scalars()
    )


@router.patch("/meters/{meter_id}", response_model=MeterOut)
async def update_meter(
    meter_id: UUID, body: MeterPatch, session: Session, actor: CurrentActor
) -> Meter:
    meter, _, prop = await get_meter(session, meter_id)
    authorize(actor, Action.METER_MANAGE, property_resource(prop))
    before = {"serial": meter.serial, "unit_label": meter.unit_label, "is_active": meter.is_active}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(meter, k, v)
    await audit(
        session,
        actor.id,
        "meter.update",
        "meter",
        meter.id,
        before,
        body.model_dump(exclude_unset=True),
    )
    return meter


def _tiers_json(body: TariffIn) -> list[dict[str, str | None]] | None:
    if body.tiers is None:
        return None
    return [
        {"up_to": None if t.up_to is None else str(t.up_to), "price": str(t.price)}
        for t in body.tiers
    ]


@router.post("/properties/{property_id}/tariffs", response_model=TariffOut, status_code=201)
async def create_tariff(
    property_id: UUID, body: TariffIn, session: Session, actor: CurrentActor
) -> Tariff:
    """Add a new price effective from a date. The currently open-ended tariff of the same kind
    is closed the day before (history is kept, never overwritten)."""
    prop, res = await get_property(session, property_id)
    authorize(actor, Action.TARIFF_MANAGE, res)
    open_prev = (
        await session.execute(
            select(Tariff).where(
                Tariff.property_id == prop.id,
                Tariff.kind == body.kind,
                Tariff.effective_to.is_(None),
                Tariff.effective_from < body.effective_from,
            )
        )
    ).scalar_one_or_none()
    before = None
    if open_prev is not None:
        before = {"id": str(open_prev.id), "effective_to": None}
        open_prev.effective_to = body.effective_from - timedelta(days=1)
        await session.flush()
    tariff = Tariff(
        property_id=prop.id,
        kind=body.kind,
        name=body.name,
        effective_from=body.effective_from,
        unit_price=body.unit_price,
        tiers=_tiers_json(body),
    )
    session.add(tariff)
    try:
        await session.flush()
    except IntegrityError as exc:
        if "ex_tariffs_no_overlap" in str(exc):
            raise Conflict(
                "Tariff dates overlap an existing tariff of this kind", code="tariff_overlap"
            ) from exc
        raise
    await audit(
        session,
        actor.id,
        "tariff.create",
        "tariff",
        tariff.id,
        before,
        {
            "kind": body.kind,
            "effective_from": body.effective_from.isoformat(),
            "unit_price": str(Decimal(body.unit_price)),
            "tiers": _tiers_json(body),
        },
    )
    return tariff


@router.get("/properties/{property_id}/tariffs", response_model=list[TariffOut])
async def list_tariffs(
    property_id: UUID, session: Session, actor: CurrentActor, kind: str | None = None
) -> list[Tariff]:
    _, res = await get_property(session, property_id)
    authorize(actor, Action.TARIFF_READ, res)
    stmt = (
        select(Tariff)
        .where(Tariff.property_id == property_id)
        .order_by(Tariff.kind, Tariff.effective_from.desc())
    )
    if kind:
        stmt = stmt.where(Tariff.kind == kind)
    return list((await session.execute(stmt)).scalars())
