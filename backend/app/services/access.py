"""Load an entity together with the ``Resource`` facts the policy needs."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policies import Resource
from app.errors import NotFound
from app.models.entities import Lease, Meter, Property, Unit


def property_resource(prop: Property, tenant_id: UUID | None = None) -> Resource:
    return Resource(owner_id=prop.owner_id, property_id=prop.id, tenant_id=tenant_id)


async def get_property(session: AsyncSession, property_id: UUID) -> tuple[Property, Resource]:
    prop = await session.get(Property, property_id)
    if prop is None:
        raise NotFound("Property not found")
    return prop, property_resource(prop)


async def get_unit(session: AsyncSession, unit_id: UUID) -> tuple[Unit, Property, Resource]:
    unit = await session.get(Unit, unit_id)
    if unit is None:
        raise NotFound("Unit not found")
    prop = await session.get(Property, unit.property_id)
    assert prop is not None
    return unit, prop, property_resource(prop)


async def get_lease(session: AsyncSession, lease_id: UUID) -> tuple[Lease, Property, Resource]:
    lease = await session.get(Lease, lease_id)
    if lease is None:
        raise NotFound("Lease not found")
    unit = await session.get(Unit, lease.unit_id)
    assert unit is not None
    prop = await session.get(Property, unit.property_id)
    assert prop is not None
    return lease, prop, property_resource(prop, lease.tenant_id)


async def get_meter(session: AsyncSession, meter_id: UUID) -> tuple[Meter, Unit, Property]:
    meter = await session.get(Meter, meter_id)
    if meter is None:
        raise NotFound("Meter not found")
    unit = await session.get(Unit, meter.unit_id)
    assert unit is not None
    prop = await session.get(Property, unit.property_id)
    assert prop is not None
    return meter, unit, prop


async def active_tenant_lease_for_unit(
    session: AsyncSession, unit_id: UUID, user_id: UUID
) -> Lease | None:
    """The tenant's non-cancelled lease on a unit (used to authorize meter/reading access)."""
    return (
        (
            await session.execute(
                select(Lease).where(
                    Lease.unit_id == unit_id,
                    Lease.tenant_id == user_id,
                    Lease.status != "cancelled",
                )
            )
        )
        .scalars()
        .first()
    )
