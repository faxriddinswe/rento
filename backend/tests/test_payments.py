import random
from datetime import date

from sqlalchemy import func, select

from app.billing.job import run_billing
from app.billing.ledger import balance
from app.db import get_sessionmaker
from app.models.entities import Invoice, LedgerEntry, Payment, PaymentAllocation
from tests.helpers import auth, make_world

RENT = 300_000_000


async def _bill(w, through="2026-03-10"):
    r = await w.client.post(
        f"/leases/{w.lease_id}/billing/run", json={"through": through}, headers=w.oh
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _pay(w, amount, paid_on="2026-03-02", **kw):
    r = await w.client.post(
        f"/leases/{w.lease_id}/payments",
        headers=w.oh,
        json={"amount": amount, "paid_on": paid_on, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _invoices(w):
    r = await w.client.get(f"/leases/{w.lease_id}/invoices", headers=w.oh)
    return sorted(r.json(), key=lambda i: i["period_start"])


async def test_partial_payment_allocates_oldest_first(client):
    w = await make_world(client)
    await _bill(w)  # Jan, Feb, Mar: 3 x RENT
    p = await _pay(w, RENT + RENT // 2)
    assert p["allocated"] == RENT + RENT // 2 and p["credit"] == 0
    jan, feb, mar = await _invoices(w)
    assert (jan["remaining"], feb["remaining"], mar["remaining"]) == (0, RENT // 2, RENT)
    bal = (await client.get(f"/leases/{w.lease_id}/balance", headers=w.th)).json()
    assert bal["balance"] == 3 * RENT - (RENT + RENT // 2) == bal["owed"] and bal["credit"] == 0


async def test_overpayment_becomes_credit_and_pays_next_invoice(client):
    w = await make_world(client)
    await _bill(w, "2026-01-05")
    p = await _pay(w, RENT + 40_000_000, paid_on="2026-01-05")
    assert p["allocated"] == RENT and p["credit"] == 40_000_000
    bal = (await client.get(f"/leases/{w.lease_id}/balance", headers=w.oh)).json()
    assert bal["balance"] == -40_000_000 and bal["credit"] == 40_000_000 and bal["owed"] == 0
    await _bill(w, "2026-02-05")  # February invoice is issued -> credit applied automatically
    feb = (await _invoices(w))[1]
    assert feb["paid"] == 40_000_000 and feb["remaining"] == RENT - 40_000_000
    assert feb["previous_balance"] == -40_000_000
    assert (await client.get(f"/leases/{w.lease_id}/balance", headers=w.oh)).json()[
        "balance"
    ] == RENT - 40_000_000
    pays = (await client.get(f"/leases/{w.lease_id}/payments", headers=w.oh)).json()
    assert pays[0]["credit"] == 0


async def test_reverse_payment_restores_debt_and_reallocates(client):
    w = await make_world(client)
    await _bill(w, "2026-02-05")
    p1 = await _pay(w, RENT, paid_on="2026-02-01")
    p2 = await _pay(w, RENT, paid_on="2026-02-02")
    assert [i["remaining"] for i in await _invoices(w)] == [0, 0]
    assert (
        await client.post(f"/payments/{p1['id']}/reverse", json={"reason": "bounced"}, headers=w.th)
    ).status_code == 403
    r = await client.post(f"/payments/{p1['id']}/reverse", json={"reason": "bounced"}, headers=w.oh)
    assert r.status_code == 200 and r.json()["reversed_at"]
    # p2 had paid Feb; Jan is open again, but reversal triggers FIFO re-application of free credit: none left
    inv = await _invoices(w)
    assert sum(i["remaining"] for i in inv) == RENT
    assert (await client.get(f"/leases/{w.lease_id}/balance", headers=w.oh)).json()[
        "balance"
    ] == RENT
    again = await client.post(f"/payments/{p1['id']}/reverse", json={"reason": "x"}, headers=w.oh)
    assert again.status_code == 409
    led = (await client.get(f"/leases/{w.lease_id}/ledger", headers=w.oh)).json()
    assert [e["entry_type"] for e in led] == [
        "invoice",
        "invoice",
        "payment",
        "payment",
        "payment_reversal",
    ]
    assert led[-1]["reverses_id"] == led[2]["id"] and led[-1]["running_balance"] == RENT
    assert p2["id"]


async def test_void_invoice_frees_payment_for_other_invoices(client):
    w = await make_world(client)
    await _bill(w, "2026-02-05")
    await _pay(w, RENT, paid_on="2026-02-01")  # pays Jan (oldest)
    jan, feb = await _invoices(w)
    r = await client.post(
        f"/invoices/{jan['id']}/void", json={"reason": "wrong rent"}, headers=w.oh
    )
    assert r.status_code == 200 and r.json()["status"] == "void" and r.json()["remaining"] == 0
    inv = await _invoices(w)
    assert inv[1]["paid"] == RENT and inv[1]["remaining"] == 0  # payment moved to February
    assert (await client.get(f"/leases/{w.lease_id}/balance", headers=w.oh)).json()["balance"] == 0
    assert (
        await client.post(f"/invoices/{jan['id']}/void", json={"reason": "x"}, headers=w.oh)
    ).status_code == 409
    assert (
        await client.post(f"/invoices/{feb['id']}/void", json={"reason": "x"}, headers=w.th)
    ).status_code == 403


async def test_payment_validation_and_permissions(client):
    w = await make_world(client)
    base = {"paid_on": "2026-02-01"}
    for bad in ({"amount": 0}, {"amount": -5}, {"amount": 10, "paid_on": "2999-01-01"}):
        r = await client.post(f"/leases/{w.lease_id}/payments", headers=w.oh, json={**base, **bad})
        assert r.status_code == 422, bad
    assert (
        await client.post(
            f"/leases/{w.lease_id}/payments", headers=w.th, json={**base, "amount": 5}
        )
    ).status_code == 403
    # manager with payment.record may record but not reverse
    await client.put(
        f"/properties/{w.prop_id}/managers",
        headers=w.oh,
        json={
            "email": "pm@demo-mail.org",
            "full_name": "PM",
            "password": "manager-pass-1",
            "permissions": ["payment.record", "payment.read"],
        },
    )
    mh = auth(
        (
            await client.post(
                "/auth/login", json={"email": "pm@demo-mail.org", "password": "manager-pass-1"}
            )
        ).json()
    )
    r = await client.post(
        f"/leases/{w.lease_id}/payments", headers=mh, json={**base, "amount": 1000}
    )
    assert r.status_code == 201
    assert (
        await client.post(f"/payments/{r.json()['id']}/reverse", json={"reason": "x"}, headers=mh)
    ).status_code == 403


async def test_tenant_cannot_see_other_tenants_money(client):
    a, b = await make_world(client), await make_world(client)
    await _bill(b, "2026-01-02")
    p = await _pay(b, 1000, paid_on="2026-01-02")
    for h in (a.th, a.oh):
        assert (await client.get(f"/leases/{b.lease_id}/ledger", headers=h)).status_code == 403
        assert (await client.get(f"/leases/{b.lease_id}/balance", headers=h)).status_code == 403
        assert (await client.get(f"/leases/{b.lease_id}/payments", headers=h)).status_code == 403
        assert (
            await client.post(f"/payments/{p['id']}/reverse", json={"reason": "x"}, headers=h)
        ).status_code == 403
        assert (
            await client.post(
                f"/leases/{b.lease_id}/payments",
                headers=h,
                json={"amount": 1, "paid_on": "2026-01-02"},
            )
        ).status_code == 403
    # own tenant can read but not write
    assert (await client.get(f"/leases/{b.lease_id}/ledger", headers=b.th)).status_code == 200
    assert (
        await client.post(
            f"/leases/{b.lease_id}/payments",
            headers=b.th,
            json={"amount": 1, "paid_on": "2026-01-02"},
        )
    ).status_code == 403


async def test_overdue_in_balance(client):
    w = await make_world(client)
    await _bill(w, "2026-01-02")  # due 2026-01-11, long overdue relative to today (2026-11)
    bal = (await client.get(f"/leases/{w.lease_id}/balance", headers=w.oh)).json()
    assert bal["overdue"] == RENT and bal["next_due_date"] is None


async def test_randomized_money_invariants(client, session):
    """Random payments/reversals/voids/invoices: ledger, allocations and credit must always agree."""
    rnd = random.Random(20260101)
    w = await make_world(client)
    maker = get_sessionmaker()
    months = [date(2026, m, 1) for m in range(1, 9)]
    payments: list[str] = []
    billed = 0
    for step in range(60):
        op = rnd.choice(["pay", "pay", "pay", "bill", "reverse", "void"])
        if op == "bill" and billed < len(months):
            await run_billing(maker, months[billed])
            billed += 1
        elif op == "pay":
            r = await client.post(
                f"/leases/{w.lease_id}/payments",
                headers=w.oh,
                json={"amount": rnd.randint(1, 2 * RENT), "paid_on": "2026-01-02"},
            )
            payments.append(r.json()["id"])
        elif op == "reverse" and payments:
            await client.post(
                f"/payments/{payments.pop(rnd.randrange(len(payments)))}/reverse",
                json={"reason": "t"},
                headers=w.oh,
            )
        elif op == "void":
            invs = [i for i in await _invoices(w) if i["status"] == "issued"]
            if invs:
                await client.post(
                    f"/invoices/{rnd.choice(invs)['id']}/void", json={"reason": "t"}, headers=w.oh
                )
        session.expire_all()
        lease_id = (await session.execute(select(Invoice.lease_id).limit(1))).scalar() or None
        if lease_id is None:
            continue
        issued = (
            await session.execute(
                select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.status == "issued")
            )
        ).scalar_one()
        active_pay = (
            await session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.reversed_at.is_(None)
                )
            )
        ).scalar_one()
        assert await balance(session, lease_id) == issued - active_pay, f"step {step} {op}"
        # allocations: per payment within [0, amount]; per invoice within [0, total]
        per_pay = (
            await session.execute(
                select(PaymentAllocation.payment_id, func.sum(PaymentAllocation.amount)).group_by(
                    PaymentAllocation.payment_id
                )
            )
        ).all()
        amounts = dict((await session.execute(select(Payment.id, Payment.amount))).all())
        reversed_ids = {
            r
            for (r,) in (
                await session.execute(select(Payment.id).where(Payment.reversed_at.is_not(None)))
            ).all()
        }
        for pid, used in per_pay:
            assert 0 <= used <= amounts[pid]
            if pid in reversed_ids:
                assert used == 0
        invs = (await session.execute(select(Invoice))).scalars().all()
        per_inv = dict(
            (
                await session.execute(
                    select(
                        PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount)
                    ).group_by(PaymentAllocation.invoice_id)
                )
            ).all()
        )
        for i in invs:
            used = per_inv.get(i.id, 0)
            assert 0 <= used <= max(i.total, 0)
            if i.status == "void":
                assert used == 0
        # FIFO completeness: unallocated credit exists only if every issued invoice is fully covered
        credit = sum(amounts[p] - used for p, used in per_pay if p not in reversed_ids) + sum(
            a
            for p, a in amounts.items()
            if p not in reversed_ids and p not in {x for x, _ in per_pay}
        )
        open_owed = sum(
            i.total - per_inv.get(i.id, 0) for i in invs if i.status == "issued" and i.total > 0
        )
        assert not (credit > 0 and open_owed > 0), (
            f"step {step}: credit {credit} but owed {open_owed}"
        )
    ledger_sum = (await session.execute(select(func.sum(LedgerEntry.amount)))).scalar_one() or 0
    assert ledger_sum == issued - active_pay
