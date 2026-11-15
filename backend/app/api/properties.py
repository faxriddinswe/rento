from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentActor, Session, authorize
from app.domain.policies import MANAGER_GRANTABLE, Action, Resource, can
from app.errors import Conflict, Unprocessable
from app.models.entities import Property, PropertyManager, Unit, User
from app.schemas import (
    ManagerIn,
    ManagerOut,
    PropertyIn,
    PropertyOut,
    PropertyPatch,
    UnitIn,
    UnitOut,
)
from app.security import hash_password
from app.services.access import get_property, get_unit
from app.services.audit import audit

router = APIRouter(tags=["properties"])


@router.post("/properties", response_model=PropertyOut, status_code=201)
async def create_property(body: PropertyIn, session: Session, actor: CurrentActor) -> Property:
    authorize(actor, Action.PROPERTY_CREATE)
    prop = Property(owner_id=actor.id, name=body.name, address=body.address)
    session.add(prop)
    await session.flush()
    await audit(session, actor.id, "property.create", "property", prop.id, after=body.model_dump())
    return prop


@router.get("/properties", response_model=list[PropertyOut])
async def list_properties(session: Session, actor: CurrentActor) -> list[Property]:
    stmt = select(Property).order_by(Property.created_at)
    if actor.role == "owner":
        stmt = stmt.where(Property.owner_id == actor.id)
    elif actor.role == "manager":
        stmt = stmt.where(Property.id.in_(list(actor.managed)))
    else:
        return []
    rows = (await session.execute(stmt)).scalars().all()
    return [p for p in rows if can(actor, Action.PROPERTY_READ, Resource(p.owner_id, p.id))]


@router.get("/properties/{property_id}", response_model=PropertyOut)
async def read_property(property_id: UUID, session: Session, actor: CurrentActor) -> Property:
    prop, res = await get_property(session, property_id)
    authorize(actor, Action.PROPERTY_READ, res)
    return prop


@router.patch("/properties/{property_id}", response_model=PropertyOut)
async def update_property(
    property_id: UUID, body: PropertyPatch, session: Session, actor: CurrentActor
) -> Property:
    prop, res = await get_property(session, property_id)
    authorize(actor, Action.PROPERTY_UPDATE, res)
    before = {"name": prop.name, "address": prop.address}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(prop, k, v)
    await audit(
        session,
        actor.id,
        "property.update",
        "property",
        prop.id,
        before,
        {"name": prop.name, "address": prop.address},
    )
    return prop


# ---- managers -------------------------------------------------------------------------------
@router.put("/properties/{property_id}/managers", response_model=ManagerOut)
async def set_manager(
    property_id: UUID, body: ManagerIn, session: Session, actor: CurrentActor
) -> ManagerOut:
    """Owner grants a user (created if new) manager access with explicit permissions."""
    prop, res = await get_property(session, property_id)
    authorize(actor, Action.MANAGER_MANAGE, res)
    allowed = {a.value for a in MANAGER_GRANTABLE}
    bad = sorted(set(body.permissions) - allowed)
    if bad:
        raise Unprocessable(f"Not grantable to managers: {', '.join(bad)}", code="bad_permission")
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        if not body.password:
            raise Unprocessable("password is required to create a new manager account")
        user = User(
            email=body.email.lower(),
            full_name=body.full_name,
            role="manager",
            password_hash=hash_password(body.password),
        )
        session.add(user)
        await session.flush()
    elif user.role != "manager":
        raise Conflict("This email belongs to a non-manager account", code="not_a_manager")
    link = await session.get(PropertyManager, (prop.id, user.id))
    before = {"permissions": link.permissions} if link else None
    if link is None:
        link = PropertyManager(property_id=prop.id, user_id=user.id, permissions=body.permissions)
        session.add(link)
    else:
        link.permissions = body.permissions
    await audit(
        session,
        actor.id,
        "manager.set",
        "property",
        prop.id,
        before,
        {"user_id": str(user.id), "permissions": body.permissions},
    )
    return ManagerOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        permissions=sorted(body.permissions),
    )


@router.get("/properties/{property_id}/managers", response_model=list[ManagerOut])
async def list_managers(
    property_id: UUID, session: Session, actor: CurrentActor
) -> list[ManagerOut]:
    _, res = await get_property(session, property_id)
    authorize(actor, Action.MANAGER_MANAGE, res)
    rows = await session.execute(
        select(PropertyManager, User)
        .join(User, User.id == PropertyManager.user_id)
        .where(PropertyManager.property_id == property_id)
    )
    return [
        ManagerOut(
            user_id=u.id, email=u.email, full_name=u.full_name, permissions=sorted(pm.permissions)
        )
        for pm, u in rows.all()
    ]


@router.delete("/properties/{property_id}/managers/{user_id}", status_code=204)
async def remove_manager(
    property_id: UUID, user_id: UUID, session: Session, actor: CurrentActor
) -> None:
    _, res = await get_property(session, property_id)
    authorize(actor, Action.MANAGER_MANAGE, res)
    link = await session.get(PropertyManager, (property_id, user_id))
    if link:
        await audit(
            session,
            actor.id,
            "manager.remove",
            "property",
            property_id,
            {"user_id": str(user_id), "permissions": link.permissions},
        )
        await session.delete(link)


# ---- units ----------------------------------------------------------------------------------
@router.post("/properties/{property_id}/units", response_model=UnitOut, status_code=201)
async def create_unit(
    property_id: UUID, body: UnitIn, session: Session, actor: CurrentActor
) -> Unit:
    _, res = await get_property(session, property_id)
    authorize(actor, Action.UNIT_MANAGE, res)
    unit = Unit(property_id=property_id, name=body.name, area_m2=body.area_m2)
    session.add(unit)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("A unit with this name already exists", code="unit_exists") from exc
    await audit(
        session, actor.id, "unit.create", "unit", unit.id, after=body.model_dump(mode="json")
    )
    return unit


@router.get("/properties/{property_id}/units", response_model=list[UnitOut])
async def list_units(property_id: UUID, session: Session, actor: CurrentActor) -> list[Unit]:
    _, res = await get_property(session, property_id)
    authorize(actor, Action.PROPERTY_READ, res)
    return list(
        (
            await session.execute(
                select(Unit).where(Unit.property_id == property_id).order_by(Unit.name)
            )
        ).scalars()
    )


@router.patch("/units/{unit_id}", response_model=UnitOut)
async def update_unit(unit_id: UUID, body: UnitIn, session: Session, actor: CurrentActor) -> Unit:
    unit, _, res = await get_unit(session, unit_id)
    authorize(actor, Action.UNIT_MANAGE, res)
    before = {"name": unit.name, "area_m2": str(unit.area_m2)}
    unit.name, unit.area_m2 = body.name, body.area_m2
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("A unit with this name already exists", code="unit_exists") from exc
    await audit(
        session,
        actor.id,
        "unit.update",
        "unit",
        unit.id,
        before,
        {"name": unit.name, "area_m2": str(unit.area_m2)},
    )
    return unit
