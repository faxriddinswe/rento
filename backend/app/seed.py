"""Seed clearly FAKE demo data (all names/emails/prices are invented; never real tariffs).

Run: uv run python -m app.seed
"""

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db import dispose_engine, get_sessionmaker
from app.models.entities import (
    Lease,
    Meter,
    MeterReading,
    Property,
    PropertyManager,
    Tariff,
    Unit,
    User,
)
from app.security import hash_password

DEMO_PASSWORD = "demo-password-FAKE"


async def seed() -> bool:
    async with get_sessionmaker()() as s:
        if (await s.execute(select(User).where(User.email == "owner@demo.demo-mail.org"))).first():
            return False
        pw = hash_password(DEMO_PASSWORD)
        owner = User(
            email="owner@demo.demo-mail.org",
            full_name="FAKE Owner",
            role="owner",
            password_hash=pw,
            phone="+000 00 000 00 00",
        )
        mgr = User(
            email="manager@demo.demo-mail.org",
            full_name="FAKE Manager",
            role="manager",
            password_hash=pw,
        )
        t1 = User(
            email="tenant1@demo.demo-mail.org",
            full_name="FAKE Tenant One",
            role="tenant",
            password_hash=pw,
        )
        t2 = User(
            email="tenant2@demo.demo-mail.org",
            full_name="FAKE Tenant Two",
            role="tenant",
            password_hash=pw,
        )
        s.add_all([owner, mgr, t1, t2])
        await s.flush()
        prop = Property(owner_id=owner.id, name="FAKE House A", address="FAKE street 1")
        s.add(prop)
        await s.flush()
        s.add(
            PropertyManager(
                property_id=prop.id,
                user_id=mgr.id,
                permissions=[
                    "reading.review",
                    "payment.record",
                    "reading.read",
                    "lease.read",
                    "property.read",
                ],
            )
        )
        u1 = Unit(property_id=prop.id, name="Apt 1")
        u2 = Unit(property_id=prop.id, name="Apt 2")
        s.add_all([u1, u2])
        await s.flush()
        # FAKE prices, minor units (tiyin) per unit of consumption.
        s.add_all(
            [
                Tariff(
                    property_id=prop.id,
                    kind="electricity",
                    name="FAKE electricity",
                    effective_from=date(2026, 1, 1),
                    unit_price=Decimal("100000"),
                ),
                Tariff(
                    property_id=prop.id,
                    kind="water_cold",
                    name="FAKE cold water",
                    effective_from=date(2026, 1, 1),
                    unit_price=Decimal("300000"),
                ),
            ]
        )
        l1 = Lease(
            unit_id=u1.id,
            tenant_id=t1.id,
            start_date=date(2026, 1, 1),
            monthly_rent=300_000_000,
            billing_day=1,
        )
        l2 = Lease(
            unit_id=u2.id,
            tenant_id=t2.id,
            start_date=date(2026, 2, 15),
            monthly_rent=250_000_000,
            billing_day=5,
        )
        s.add_all([l1, l2])
        m1 = Meter(unit_id=u1.id, kind="electricity", serial="FAKE-E-001", unit_label="kWh")
        m2 = Meter(unit_id=u1.id, kind="water_cold", serial="FAKE-W-001", unit_label="m3")
        s.add_all([m1, m2])
        await s.flush()
        s.add_all(
            [
                MeterReading(
                    meter_id=m1.id,
                    lease_id=l1.id,
                    submitted_by=t1.id,
                    value=Decimal("1000"),
                    reading_date=date(2026, 1, 1),
                    status="confirmed",
                    is_baseline=True,
                ),
                MeterReading(
                    meter_id=m2.id,
                    lease_id=l1.id,
                    submitted_by=t1.id,
                    value=Decimal("50"),
                    reading_date=date(2026, 1, 1),
                    status="confirmed",
                    is_baseline=True,
                ),
            ]
        )
        await s.commit()
        return True


async def main() -> None:
    created = await seed()
    print("seeded FAKE demo data" if created else "already seeded")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
