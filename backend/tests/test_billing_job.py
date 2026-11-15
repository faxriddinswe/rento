"""Billing job on real PostgreSQL: idempotency, ledger, readings, pending/catch-up, final invoice."""

import asyncio
from datetime import date

from sqlalchemy import func, select

from app.billing.job import run_billing
from app.billing.ledger import balance
from app.db import get_sessionmaker
from app.models.entities import Invoice, InvoiceLine, LedgerEntry, Notification
from tests.helpers import baseline, make_meter, make_world, submit

RENT = 300_000_000


async def _tariff(w, kind="electricity", price="100000", frm="2026-01-01"):
    r = await w.client.post(
        f"/properties/{w.prop_id}/tariffs",
        headers=w.oh,
        json={"kind": kind, "effective_from": frm, "unit_price": price},
    )
    assert r.status_code == 201, r.text


async def _invoices(session, lease_id):
    session.expire_all()
    return (
        (
            await session.execute(
                select(Invoice).where(Invoice.lease_id == lease_id).order_by(Invoice.period_start)
            )
        )
        .scalars()
        .all()
    )


async def test_job_creates_invoice_once_and_posts_ledger(client, session):
    w = await make_world(client, with_tenant=True)
    maker = get_sessionmaker()
    s1 = await run_billing(maker, date(2026, 1, 1))
    assert (s1.created, s1.exists) == (1, 0)
    s2 = await run_billing(maker, date(2026, 1, 1))
    assert (s2.created, s2.exists) == (0, 1)
    invs = await _invoices(session, w.lease_id)
    assert len(invs) == 1 and invs[0].total == RENT and invs[0].number.startswith("INV-")
    assert await balance(session, invs[0].lease_id) == RENT
    # tenant notified once
    notes = (
        (await session.execute(select(Notification).where(Notification.kind == "invoice_issued")))
        .scalars()
        .all()
    )
    assert len(notes) == 1


async def test_concurrent_runs_never_duplicate(client, session):
    w = await make_world(client)
    maker = get_sessionmaker()
    results = await asyncio.gather(*[run_billing(maker, date(2026, 2, 1)) for _ in range(5)])
    # Feb 1 is a billing day; Jan 1 is outside the 7-day window -> exactly 1 invoice in total
    assert sum(r.created for r in results) == 1
    assert len(await _invoices(session, w.lease_id)) == 1


async def test_catch_up_window_covers_missed_days(client, session):
    w = await make_world(client)
    await run_billing(get_sessionmaker(), date(2026, 2, 5))  # job was down on Feb 1..4
    invs = await _invoices(session, w.lease_id)
    assert [i.period_start for i in invs] == [date(2026, 2, 1)]
    await run_billing(get_sessionmaker(), date(2026, 2, 5))
    assert len(await _invoices(session, w.lease_id)) == 1


async def test_non_billing_day_creates_nothing(client, session):
    w = await make_world(client, start="2026-01-01")
    s = await run_billing(get_sessionmaker(), date(2026, 3, 15), catch_up_days=1)
    assert s.created == 0
    assert await _invoices(session, w.lease_id) == []


async def test_utility_billing_end_to_end(client, session, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await _tariff(w)
    await baseline(w, m, "1000", "2026-01-01")
    maker = get_sessionmaker()
    await run_billing(maker, date(2026, 1, 1))
    await submit(w, storage, m, "1120.5", "2026-02-01", confirm=True)
    s = await run_billing(maker, date(2026, 2, 1))
    assert s.created == 1
    inv = (await _invoices(session, w.lease_id))[-1]
    lines = (
        (
            await session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == inv.id)
                .order_by(InvoiceLine.sort)
            )
        )
        .scalars()
        .all()
    )
    assert [x.kind for x in lines] == ["rent", "utility"]
    assert lines[1].amount == 12_050_000 and inv.total == RENT + 12_050_000
    assert inv.previous_balance == RENT  # January rent still unpaid
    assert await balance(session, w.lease_id) == 2 * RENT + 12_050_000
    # next month consumption starts from the last BILLED reading
    await submit(w, storage, m, "1130.5", "2026-03-01", confirm=True)
    await run_billing(maker, date(2026, 3, 1))
    mar = (await _invoices(session, w.lease_id))[-1]
    mline = (
        await session.execute(
            select(InvoiceLine).where(
                InvoiceLine.invoice_id == mar.id, InvoiceLine.kind == "utility"
            )
        )
    ).scalar_one()
    assert mline.quantity == 10 and mline.amount == 1_000_000


async def test_pending_reading_then_catch_up_adjustment(client, session, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await _tariff(w)
    await baseline(w, m, "1000", "2026-01-01")
    maker = get_sessionmaker()
    await run_billing(maker, date(2026, 1, 1))
    await run_billing(maker, date(2026, 2, 1))  # tenant forgot the reading
    feb = (await _invoices(session, w.lease_id))[-1]
    feb_id = feb.id
    pend = (
        await session.execute(
            select(InvoiceLine).where(InvoiceLine.invoice_id == feb.id, InvoiceLine.meter_id == m)
        )
    ).scalar_one()
    assert pend.pending_reading and pend.amount == 0 and feb.total == RENT
    kinds = {n.kind for n in (await session.execute(select(Notification))).scalars()}
    assert {"reading_pending", "reading_reminder"} <= kinds
    # reading arrives late; the issued Feb invoice is untouched, March carries a catch-up line
    await submit(w, storage, m, "1200", "2026-02-20", confirm=True)
    await run_billing(maker, date(2026, 3, 1))
    session.expire_all()
    feb2 = await session.get(Invoice, feb_id)
    assert feb2.total == RENT
    mar = (await _invoices(session, w.lease_id))[-1]
    adj = (
        await session.execute(
            select(InvoiceLine).where(
                InvoiceLine.invoice_id == mar.id, InvoiceLine.kind == "adjustment"
            )
        )
    ).scalar_one()
    assert adj.amount == 20_000_000 and not adj.pending_reading


async def test_missing_tariff_skips_invoice_and_notifies_owner(client, session, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m, "10", "2026-01-01")
    maker = get_sessionmaker()
    await run_billing(maker, date(2026, 1, 1))
    await submit(w, storage, m, "20", "2026-02-01", confirm=True)
    s = await run_billing(maker, date(2026, 2, 1))
    assert s.missing_tariff == 1 and s.created == 0
    assert len(await _invoices(session, w.lease_id)) == 1
    n = (
        (await session.execute(select(Notification).where(Notification.kind == "billing_failed")))
        .scalars()
        .all()
    )
    assert len(n) == 1
    await run_billing(maker, date(2026, 2, 1))
    n = (
        (await session.execute(select(Notification).where(Notification.kind == "billing_failed")))
        .scalars()
        .all()
    )
    assert len(n) == 1  # idempotent notification
    # owner adds the tariff -> next run bills it
    await _tariff(w, price="50000")
    s = await run_billing(maker, date(2026, 2, 2))
    assert s.created == 1


async def test_prorated_first_invoice_via_job(client, session):
    w = await make_world(client, start="2026-02-15")
    await client.post(f"/leases/{w.lease_id}/end", json={"end_date": "2026-12-31"}, headers=w.oh)
    s = await run_billing(get_sessionmaker(), date(2026, 2, 15))
    assert s.created == 1
    inv = (await _invoices(session, w.lease_id))[0]
    # billing_day=1: cycle Feb 1 - Mar 1 (28 days), period Feb 15 - Feb 28 = 14 days
    assert inv.total == RENT * 14 // 28


async def test_final_invoice_after_lease_end(client, session, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await _tariff(w)
    await baseline(w, m, "0", "2026-01-01")
    maker = get_sessionmaker()
    await run_billing(maker, date(2026, 1, 1))
    await client.post(f"/leases/{w.lease_id}/end", json={"end_date": "2026-01-20"}, headers=w.oh)
    await submit(w, storage, m, "30", "2026-01-20", confirm=True)
    s = await run_billing(maker, date(2026, 1, 21))
    assert s.created == 1
    final = (await _invoices(session, w.lease_id))[-1]
    assert final.period_start == date(2026, 1, 21) and final.total == 3_000_000
    again = await run_billing(maker, date(2026, 1, 21))
    assert again.created == 0


async def test_adjustment_goes_on_next_invoice_only(client, session):
    w = await make_world(client)
    r = await client.post(
        f"/leases/{w.lease_id}/adjustments",
        headers=w.oh,
        json={"amount": -5_000_000, "description": "Discount for repair"},
    )
    assert r.status_code == 201
    assert (
        await client.post(
            f"/leases/{w.lease_id}/adjustments",
            headers=w.th,
            json={"amount": 5, "description": "x"},
        )
    ).status_code == 403
    maker = get_sessionmaker()
    await run_billing(maker, date(2026, 1, 1))
    inv = (await _invoices(session, w.lease_id))[0]
    assert inv.total == RENT - 5_000_000
    await run_billing(maker, date(2026, 2, 1))
    assert (await _invoices(session, w.lease_id))[1].total == RENT  # applied once


async def test_backfill_endpoint_bills_oldest_first_and_is_idempotent(client, session):
    w = await make_world(client, start="2026-01-01")
    r = await client.post(
        f"/leases/{w.lease_id}/billing/run", json={"through": "2026-03-10"}, headers=w.oh
    )
    assert r.status_code == 200 and r.json()["created"] == 3
    r = await client.post(
        f"/leases/{w.lease_id}/billing/run", json={"through": "2026-03-10"}, headers=w.oh
    )
    assert r.json()["created"] == 0 and r.json()["exists"] == 3
    assert (
        await client.post(f"/leases/{w.lease_id}/billing/run", json={}, headers=w.th)
    ).status_code == 403
    invs = (await client.get(f"/leases/{w.lease_id}/invoices", headers=w.th)).json()
    assert [i["period_start"] for i in invs] == ["2026-03-01", "2026-02-01", "2026-01-01"]
    assert invs[0]["lines"][0]["kind"] == "rent"
    one = (await client.get(f"/invoices/{invs[0]['id']}", headers=w.th)).json()
    assert one["remaining"] == RENT and one["paid"] == 0


async def test_invoice_tenant_isolation(client):
    a = await make_world(client)
    b = await make_world(client)
    await client.post(
        f"/leases/{b.lease_id}/billing/run", json={"through": "2026-01-02"}, headers=b.oh
    )
    inv = (await client.get(f"/leases/{b.lease_id}/invoices", headers=b.oh)).json()[0]
    for h in (a.th, a.oh):
        assert (await client.get(f"/invoices/{inv['id']}", headers=h)).status_code == 403
        assert (await client.get(f"/leases/{b.lease_id}/invoices", headers=h)).status_code == 403


async def test_db_invariants_total_equals_lines(client, session):
    w = await make_world(client)
    await client.post(
        f"/leases/{w.lease_id}/billing/run", json={"through": "2026-06-01"}, headers=w.oh
    )
    rows = (
        await session.execute(
            select(Invoice.number, Invoice.total, func.sum(InvoiceLine.amount))
            .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
            .group_by(Invoice.id)
        )
    ).all()
    assert rows and all(t == s for _, t, s in rows)
    led = (await session.execute(select(func.sum(LedgerEntry.amount)))).scalar_one()
    assert led == sum(t for _, t, _ in rows)
