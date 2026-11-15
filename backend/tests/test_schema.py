"""DB-level guarantees on a real PostgreSQL: constraints and triggers, not app code."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.entities import (
    Invoice,
    InvoiceLine,
    Lease,
    LedgerEntry,
    Property,
    Tariff,
    Unit,
    User,
)


async def _base(session):
    owner = User(email="o@example.test", full_name="Owner", role="owner")
    session.add(owner)
    await session.flush()
    prop = Property(owner_id=owner.id, name="P")
    session.add(prop)
    await session.flush()
    unit = Unit(property_id=prop.id, name="1")
    session.add(unit)
    await session.flush()
    return owner, prop, unit


def _lease(unit, start, end, status="active"):
    return Lease(unit_id=unit.id, start_date=start, end_date=end, monthly_rent=100, status=status)


async def test_overlapping_leases_rejected(session):
    _, _, unit = await _base(session)
    session.add(_lease(unit, date(2026, 1, 1), date(2026, 6, 30)))
    await session.flush()
    session.add(_lease(unit, date(2026, 6, 30), None))  # touches last day -> overlap
    with pytest.raises(IntegrityError, match="ex_leases_no_overlap"):
        await session.flush()


async def test_adjacent_and_cancelled_leases_allowed(session):
    _, _, unit = await _base(session)
    session.add(_lease(unit, date(2026, 1, 1), date(2026, 6, 30)))
    session.add(_lease(unit, date(2026, 7, 1), None))
    session.add(_lease(unit, date(2026, 2, 1), date(2026, 3, 1), status="cancelled"))
    await session.flush()


async def test_open_ended_lease_blocks_future_lease(session):
    _, _, unit = await _base(session)
    session.add(_lease(unit, date(2026, 1, 1), None))
    await session.flush()
    session.add(_lease(unit, date(2030, 1, 1), None))
    with pytest.raises(IntegrityError, match="ex_leases_no_overlap"):
        await session.flush()


async def test_tariff_overlap_rejected_but_other_kind_ok(session):
    _, prop, _ = await _base(session)
    t = lambda kind, a, b: Tariff(  # noqa: E731
        property_id=prop.id, kind=kind, effective_from=a, effective_to=b, unit_price=100
    )
    session.add(t("electricity", date(2026, 1, 1), date(2026, 3, 31)))
    session.add(t("water_cold", date(2026, 1, 1), None))
    await session.flush()
    session.add(t("electricity", date(2026, 3, 31), None))
    with pytest.raises(IntegrityError, match="ex_tariffs_no_overlap"):
        await session.flush()


async def test_ledger_is_append_only(session):
    _, _, unit = await _base(session)
    lease = _lease(unit, date(2026, 1, 1), None)
    session.add(lease)
    await session.flush()
    entry = LedgerEntry(
        lease_id=lease.id, entry_type="invoice", amount=500, ref_type="invoice", ref_id=uuid.uuid4()
    )
    session.add(entry)
    await session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text("UPDATE ledger_entries SET amount = 1"))
    await session.rollback()


async def _invoice(session, total, line_amounts):
    _, _, unit = await _base(session)
    lease = _lease(unit, date(2026, 1, 1), None)
    session.add(lease)
    await session.flush()
    inv = Invoice(
        lease_id=lease.id,
        number="N-1",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        issue_date=date(2026, 3, 1),
        due_date=date(2026, 3, 10),
        total=total,
    )
    session.add(inv)
    await session.flush()
    for i, a in enumerate(line_amounts):
        session.add(InvoiceLine(invoice_id=inv.id, sort=i, kind="rent", description="x", amount=a))
    await session.flush()
    return inv


async def test_invoice_total_must_equal_sum_of_lines(session):
    await _invoice(session, 300, [100, 200])
    await session.commit()  # deferred trigger passes


async def test_invoice_total_mismatch_fails_on_commit(session):
    await _invoice(session, 999, [100, 200])
    with pytest.raises(DBAPIError, match="sum of lines"):
        await session.commit()


async def test_issued_invoice_is_immutable_except_status(session):
    inv = await _invoice(session, 300, [100, 200])
    inv_id = inv.id
    await session.commit()
    with pytest.raises(DBAPIError, match="immutable"):
        await session.execute(text("UPDATE invoices SET total = 1"))
    await session.rollback()
    await session.execute(text("UPDATE invoices SET status = 'void' WHERE id = :i"), {"i": inv_id})
    await session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text("UPDATE invoice_lines SET amount = 5"))
    await session.rollback()
