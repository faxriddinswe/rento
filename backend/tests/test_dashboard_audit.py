from datetime import date

from app.services.clock import today_local
from tests.helpers import auth, make_world, signup

RENT = 300_000_000


async def test_dashboard_numbers_and_overdue(client):
    today = today_local()
    w = await make_world(client, start=today.replace(day=1).isoformat())
    await client.post(f"/leases/{w.lease_id}/billing/run", json={}, headers=w.oh)
    await client.post(
        f"/leases/{w.lease_id}/payments",
        headers=w.oh,
        json={"amount": 100_000_000, "paid_on": today.isoformat()},
    )
    d = (await client.get("/dashboard", headers=w.oh)).json()
    assert d["month"] == today.strftime("%Y-%m")
    assert d["expected"] == RENT and d["collected"] == 100_000_000
    assert d["outstanding"] == RENT - 100_000_000 and d["active_leases"] == 1
    # an old unpaid lease shows up as overdue
    old = await make_world(client, start="2026-01-01")
    await client.post(
        f"/leases/{old.lease_id}/billing/run", json={"through": "2026-01-02"}, headers=old.oh
    )
    d = (await client.get("/dashboard", headers=old.oh)).json()
    assert d["overdue"][0]["overdue"] == RENT and d["overdue"][0]["tenant_name"] == "FAKE Tenant"
    # dashboards are scoped to the caller's own properties
    mine = (await client.get("/dashboard", headers=w.oh)).json()
    assert [r["lease_id"] for r in mine["overdue"]] == [w.lease_id]  # never the other owner's lease


async def test_dashboard_forbidden_for_tenant_and_empty_for_stranger(client):
    w = await make_world(client)
    assert (await client.get("/dashboard", headers=w.th)).status_code == 403
    s = await signup(client)
    d = (await client.get("/dashboard", headers=auth(s))).json()
    assert d["expected"] == 0 and d["overdue"] == []
    assert (await client.get("/dashboard")).status_code == 401


async def test_audit_log_covers_money_actions_and_is_scoped(client):
    a = await make_world(client)
    b = await make_world(client)
    await client.post(
        f"/leases/{a.lease_id}/billing/run", json={"through": "2026-01-02"}, headers=a.oh
    )
    r = await client.post(
        f"/leases/{a.lease_id}/payments",
        headers=a.oh,
        json={"amount": 5000, "paid_on": "2026-01-02"},
    )
    await client.post(f"/payments/{r.json()['id']}/reverse", json={"reason": "oops"}, headers=a.oh)
    await client.post(
        f"/properties/{a.prop_id}/tariffs",
        headers=a.oh,
        json={"kind": "gas", "effective_from": "2026-01-01", "unit_price": "10"},
    )
    rows = (await client.get("/audit", headers=a.oh)).json()
    actions = {x["action"] for x in rows}
    assert {
        "invoice.create",
        "payment.record",
        "payment.reverse",
        "tariff.create",
        "lease.create",
        "billing.run",
        "invite.accept",
        "user.signup",
    } <= actions
    pay = next(x for x in rows if x["action"] == "payment.record")
    assert (
        pay["actor_id"]
        and pay["after"]["amount"] == 5000
        and pay["request_id"]
        and pay["created_at"]
    )
    rev = next(x for x in rows if x["action"] == "payment.reverse")
    assert rev["before"] == {"amount": 5000} and rev["after"]["reason"] == "oops"
    # system-made invoices belong to the owner too; B never sees A's rows and vice versa
    inv = next(x for x in rows if x["action"] == "invoice.create")
    assert inv["after"]["total"] == RENT
    b_rows = (await client.get("/audit", headers=b.oh)).json()
    assert all(x["id"] not in {y["id"] for y in rows} for x in b_rows)
    # filters
    only = (await client.get("/audit", params={"action": "payment.record"}, headers=a.oh)).json()
    assert [x["action"] for x in only] == ["payment.record"]


async def test_audit_forbidden_for_tenant_and_manager(client):
    w = await make_world(client)
    assert (await client.get("/audit", headers=w.th)).status_code == 403
    await client.put(
        f"/properties/{w.prop_id}/managers",
        headers=w.oh,
        json={
            "email": "am@demo-mail.org",
            "full_name": "M",
            "password": "manager-pass-1",
            "permissions": ["property.read"],
        },
    )
    mh = auth(
        (
            await client.post(
                "/auth/login", json={"email": "am@demo-mail.org", "password": "manager-pass-1"}
            )
        ).json()
    )
    assert (await client.get("/audit", headers=mh)).status_code == 403
    assert date.today()
