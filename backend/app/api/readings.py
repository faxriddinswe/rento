import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentActor, Session, StorageDep, authorize
from app.config import get_settings
from app.domain.policies import Action, Resource, can
from app.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.models.entities import Lease, Meter, MeterReading, Property, Unit
from app.schemas import (
    BaselineIn,
    ConfirmIn,
    PhotoUploadIn,
    PhotoUploadOut,
    ReadingIn,
    ReadingOut,
    RejectIn,
)
from app.services.access import active_tenant_lease_for_unit, get_meter, property_resource
from app.services.audit import audit
from app.services.clock import today_local
from app.services.notifications import enqueue
from app.services.readings import (
    ALLOWED_TYPES,
    EXT,
    check_monotonic,
    lease_on_date,
    tenant_prefix,
)

router = APIRouter(tags=["readings"])


async def _out(storage: StorageDep, r: MeterReading) -> ReadingOut:
    out = ReadingOut.model_validate(r)
    if r.photo_key:
        out.photo_url = await storage.presign_get(r.photo_key)
    return out


async def _tenant_lease_or_403(session: Session, unit: Unit, actor_id: UUID) -> Lease:
    lease = await active_tenant_lease_for_unit(session, unit.id, actor_id)
    if lease is None:
        raise Forbidden("You have no lease on this meter's unit")
    return lease


def _snap(r: MeterReading) -> dict[str, object]:
    return {
        "meter_id": str(r.meter_id),
        "value": str(r.value),
        "date": r.reading_date.isoformat(),
        "status": r.status,
        "is_baseline": r.is_baseline,
    }


@router.post("/meters/{meter_id}/photo-upload", response_model=PhotoUploadOut)
async def photo_upload(
    meter_id: UUID, body: PhotoUploadIn, session: Session, actor: CurrentActor, storage: StorageDep
) -> PhotoUploadOut:
    """Step 1 (tenant): get a presigned POST that lets the browser upload straight to storage."""
    _, unit, prop = await get_meter(session, meter_id)
    lease = await _tenant_lease_or_403(session, unit, actor.id) if actor.role == "tenant" else None
    authorize(
        actor, Action.READING_SUBMIT, property_resource(prop, lease.tenant_id if lease else None)
    )
    max_bytes = get_settings().max_photo_bytes
    if body.size > max_bytes:
        raise Unprocessable(f"Photo too large (max {max_bytes} bytes)", code="photo_too_large")
    key = f"{tenant_prefix(actor.id)}{uuid.uuid4()}.{EXT[body.content_type]}"
    post = await storage.presign_post(key, body.content_type, max_bytes)
    return PhotoUploadOut(url=post.url, fields=post.fields, key=post.key, max_bytes=max_bytes)


@router.post("/meters/{meter_id}/readings", response_model=ReadingOut, status_code=201)
async def submit_reading(
    meter_id: UUID, body: ReadingIn, session: Session, actor: CurrentActor, storage: StorageDep
) -> ReadingOut:
    """Step 2 (tenant): submit the value with the uploaded photo's key."""
    meter, unit, prop = await get_meter(session, meter_id)
    lease = await _tenant_lease_or_403(session, unit, actor.id) if actor.role == "tenant" else None
    authorize(
        actor, Action.READING_SUBMIT, property_resource(prop, lease.tenant_id if lease else None)
    )
    assert lease is not None  # only tenants pass READING_SUBMIT
    if not meter.is_active:
        raise Conflict("Meter is not active", code="meter_inactive")
    if not body.photo_key.startswith(tenant_prefix(actor.id)):
        raise Forbidden("Photo key does not belong to you", code="photo_key_forbidden")
    info = await storage.head(body.photo_key)
    if info is None:
        raise Unprocessable("Photo was not uploaded", code="photo_missing")
    if info.content_type not in ALLOWED_TYPES:
        raise Unprocessable("Unsupported photo type", code="photo_type")
    if info.size > get_settings().max_photo_bytes:
        raise Unprocessable("Photo too large", code="photo_too_large")
    if body.reading_date > today_local():
        raise Unprocessable("Reading date is in the future", code="reading_future")
    if body.reading_date < lease.start_date or (
        lease.end_date and body.reading_date > lease.end_date
    ):
        raise Unprocessable(
            "Reading date is outside your lease period", code="reading_outside_lease"
        )
    dup = await session.scalar(
        select(MeterReading.id).where(
            MeterReading.meter_id == meter.id,
            MeterReading.reading_date == body.reading_date,
            MeterReading.status.in_(("pending", "confirmed")),
        )
    )
    if dup:
        raise Conflict("A reading for this meter and date already exists", code="reading_duplicate")
    await check_monotonic(session, meter.id, body.value, body.reading_date)
    reading = MeterReading(
        meter_id=meter.id,
        lease_id=lease.id,
        submitted_by=actor.id,
        value=body.value,
        reading_date=body.reading_date,
        photo_key=body.photo_key,
    )
    session.add(reading)
    await session.flush()
    await audit(session, actor.id, "reading.submit", "reading", reading.id, after=_snap(reading))
    return await _out(storage, reading)


async def _load_reading(
    session: Session, reading_id: UUID
) -> tuple[MeterReading, Meter, Unit, Property, Resource]:
    reading = await session.get(MeterReading, reading_id)
    if reading is None:
        raise NotFound("Reading not found")
    meter, unit, prop = await get_meter(session, reading.meter_id)
    tenant_id = None
    if reading.lease_id:
        lease = await session.get(Lease, reading.lease_id)
        tenant_id = lease.tenant_id if lease else None
    return reading, meter, unit, prop, property_resource(prop, tenant_id)


@router.get("/readings", response_model=list[ReadingOut])
async def list_readings(
    session: Session,
    actor: CurrentActor,
    storage: StorageDep,
    status: str | None = None,
    meter_id: UUID | None = None,
    property_id: UUID | None = None,
) -> list[ReadingOut]:
    """Owner/manager: reading inbox (e.g. status=pending). Tenant: own lease's readings."""
    stmt = (
        select(MeterReading, Lease, Property)
        .join(Meter, Meter.id == MeterReading.meter_id)
        .join(Unit, Unit.id == Meter.unit_id)
        .join(Property, Property.id == Unit.property_id)
        .outerjoin(Lease, Lease.id == MeterReading.lease_id)
        .order_by(MeterReading.reading_date.desc(), MeterReading.created_at.desc())
        .limit(500)
    )
    if status:
        stmt = stmt.where(MeterReading.status == status)
    if meter_id:
        stmt = stmt.where(MeterReading.meter_id == meter_id)
    if property_id:
        stmt = stmt.where(Property.id == property_id)
    if actor.role == "owner":
        stmt = stmt.where(Property.owner_id == actor.id)
    elif actor.role == "manager":
        stmt = stmt.where(Property.id.in_(list(actor.managed)))
    else:
        stmt = stmt.where(Lease.tenant_id == actor.id)
    out = []
    for reading, lease, prop in (await session.execute(stmt)).all():
        res = Resource(prop.owner_id, prop.id, lease.tenant_id if lease else None)
        if can(actor, Action.READING_READ, res):
            out.append(await _out(storage, reading))
    return out


@router.post("/readings/{reading_id}/confirm", response_model=ReadingOut)
async def confirm_reading(
    reading_id: UUID, body: ConfirmIn, session: Session, actor: CurrentActor, storage: StorageDep
) -> ReadingOut:
    reading, meter, _, _, res = await _load_reading(session, reading_id)
    authorize(actor, Action.READING_REVIEW, res)
    if reading.status != "pending":
        raise Conflict("Only pending readings can be confirmed", code="reading_not_pending")
    before = _snap(reading)
    if body.meter_replaced:
        reading.is_baseline = True
        reading.replaced_final_value = body.replaced_final_value
    else:
        await check_monotonic(session, meter.id, reading.value, reading.reading_date, reading.id)
    reading.status = "confirmed"
    reading.reviewed_by, reading.reviewed_at = actor.id, datetime.now(UTC)
    await session.flush()
    await audit(session, actor.id, "reading.confirm", "reading", reading.id, before, _snap(reading))
    return await _out(storage, reading)


@router.post("/readings/{reading_id}/reject", response_model=ReadingOut)
async def reject_reading(
    reading_id: UUID, body: RejectIn, session: Session, actor: CurrentActor, storage: StorageDep
) -> ReadingOut:
    reading, _, _, _, res = await _load_reading(session, reading_id)
    authorize(actor, Action.READING_REVIEW, res)
    if reading.status != "pending":
        raise Conflict("Only pending readings can be rejected", code="reading_not_pending")
    before = _snap(reading)
    reading.status, reading.reject_reason = "rejected", body.reason
    reading.reviewed_by, reading.reviewed_at = actor.id, datetime.now(UTC)
    await session.flush()
    await enqueue(
        session,
        reading.submitted_by,
        "reading_rejected",
        f"reading_rejected:{reading.id}",
        {
            "reading_id": str(reading.id),
            "reason": body.reason,
            "value": str(reading.value),
            "date": reading.reading_date.isoformat(),
        },
    )
    await audit(session, actor.id, "reading.reject", "reading", reading.id, before, _snap(reading))
    return await _out(storage, reading)


@router.post("/meters/{meter_id}/baseline", response_model=ReadingOut, status_code=201)
async def record_baseline(
    meter_id: UUID, body: BaselineIn, session: Session, actor: CurrentActor, storage: StorageDep
) -> ReadingOut:
    """Owner/manager: first reading or 'meter replaced' — a confirmed reading that resets the baseline.
    ``replaced_final_value`` is the old meter's last value (consumption up to it is still billed)."""
    meter, unit, prop = await get_meter(session, meter_id)
    lease = await lease_on_date(session, unit.id, body.reading_date)
    res = property_resource(prop, lease.tenant_id if lease else None)
    authorize(actor, Action.READING_REVIEW, res)
    dup = await session.scalar(
        select(MeterReading.id).where(
            MeterReading.meter_id == meter.id,
            MeterReading.reading_date == body.reading_date,
            MeterReading.status.in_(("pending", "confirmed")),
        )
    )
    if dup:
        raise Conflict("A reading for this meter and date already exists", code="reading_duplicate")
    if body.replaced_final_value is not None:
        await check_monotonic(session, meter.id, body.replaced_final_value, body.reading_date)
    reading = MeterReading(
        meter_id=meter.id,
        lease_id=lease.id if lease else None,
        submitted_by=actor.id,
        value=Decimal(body.value),
        reading_date=body.reading_date,
        status="confirmed",
        is_baseline=True,
        replaced_final_value=body.replaced_final_value,
        reviewed_by=actor.id,
        reviewed_at=datetime.now(UTC),
    )
    session.add(reading)
    await session.flush()
    await audit(session, actor.id, "reading.baseline", "reading", reading.id, after=_snap(reading))
    return await _out(storage, reading)
