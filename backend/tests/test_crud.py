from tests.helpers import auth, make_world, signup


async def test_property_unit_lease_flow_and_overlap(client):
    w = await make_world(client, with_tenant=False)
    # second lease overlapping -> 409
    r = await client.post(
        f"/units/{w.unit_id}/leases",
        json={"start_date": "2026-06-01", "monthly_rent": 1},
        headers=w.oh,
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "lease_overlap"
    # end first lease, then a later one is fine
    r = await client.post(
        f"/leases/{w.lease_id}/end", json={"end_date": "2026-05-31"}, headers=w.oh
    )
    assert r.status_code == 200 and r.json()["status"] == "ended"
    r = await client.post(
        f"/units/{w.unit_id}/leases",
        json={"start_date": "2026-06-01", "monthly_rent": 1},
        headers=w.oh,
    )
    assert r.status_code == 201
    leases = (await client.get("/leases", headers=w.oh)).json()
    assert len(leases) == 2


async def test_duplicate_unit_name_and_validation(client):
    w = await make_world(client, with_tenant=False)
    r = await client.post(f"/properties/{w.prop_id}/units", json={"name": "Apt 1"}, headers=w.oh)
    assert r.status_code == 409
    r = await client.post(
        f"/units/{w.unit_id}/leases",
        json={"start_date": "2026-02-01", "end_date": "2026-01-01", "monthly_rent": 1},
        headers=w.oh,
    )
    assert r.status_code == 422
    r = await client.post(
        f"/units/{w.unit_id}/leases",
        json={"start_date": "2030-02-01", "monthly_rent": -5},
        headers=w.oh,
    )
    assert r.status_code == 422


async def test_tariff_history_closes_previous(client):
    w = await make_world(client, with_tenant=False)
    url = f"/properties/{w.prop_id}/tariffs"
    mk = lambda frm, price: client.post(  # noqa: E731
        url, json={"kind": "electricity", "effective_from": frm, "unit_price": price}, headers=w.oh
    )
    assert (await mk("2026-01-01", "100000")).status_code == 201
    assert (await mk("2026-04-01", "120000")).status_code == 201
    rows = (await client.get(url, params={"kind": "electricity"}, headers=w.oh)).json()
    assert [(r["effective_from"], r["effective_to"]) for r in rows] == [
        ("2026-04-01", None),
        ("2026-01-01", "2026-03-31"),
    ]
    # inserting a tariff in the past that overlaps existing history -> 409
    r = await mk("2026-02-01", "1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "tariff_overlap"


async def test_tariff_tiers_validation(client):
    w = await make_world(client, with_tenant=False)
    url = f"/properties/{w.prop_id}/tariffs"
    base = {"kind": "electricity", "effective_from": "2026-01-01", "unit_price": "0"}
    good = [{"up_to": "100", "price": "100000"}, {"up_to": None, "price": "200000"}]
    assert (await client.post(url, json={**base, "tiers": good}, headers=w.oh)).status_code == 201
    for bad in (
        [{"up_to": "100", "price": "1"}],  # last tier closed
        [{"up_to": None, "price": "1"}, {"up_to": None, "price": "2"}],  # open tier not last
        [
            {"up_to": "100", "price": "1"},
            {"up_to": "50", "price": "2"},
            {"up_to": None, "price": "3"},
        ],
    ):
        r = await client.post(url, json={**base, "kind": "gas", "tiers": bad}, headers=w.oh)
        assert r.status_code == 422, bad


async def test_meters_crud_and_tenant_can_read_own_unit_meters(client):
    w = await make_world(client)
    r = await client.post(
        f"/units/{w.unit_id}/meters",
        json={"kind": "electricity", "unit_label": "kWh"},
        headers=w.oh,
    )
    assert r.status_code == 201
    mid = r.json()["id"]
    assert (await client.patch(f"/meters/{mid}", json={"serial": "S1"}, headers=w.oh)).json()[
        "serial"
    ] == "S1"
    r = await client.get(f"/units/{w.unit_id}/meters", headers=w.th)
    assert r.status_code == 200 and len(r.json()) == 1
    # tenant cannot create meters
    r = await client.post(f"/units/{w.unit_id}/meters", json={"kind": "gas"}, headers=w.th)
    assert r.status_code == 403


async def test_manager_permissions_are_enforced(client):
    w = await make_world(client, with_tenant=False)
    r = await client.put(
        f"/properties/{w.prop_id}/managers",
        json={
            "email": "mgr@demo-mail.org",
            "full_name": "FAKE Mgr",
            "password": "manager-pass-1",
            "permissions": ["property.read", "lease.read"],
        },
        headers=w.oh,
    )
    assert r.status_code == 200, r.text
    tok = (
        await client.post(
            "/auth/login", json={"email": "mgr@demo-mail.org", "password": "manager-pass-1"}
        )
    ).json()
    mh = auth(tok)
    assert (await client.get(f"/properties/{w.prop_id}", headers=mh)).status_code == 200
    assert (await client.get(f"/leases/{w.lease_id}", headers=mh)).status_code == 200
    assert (
        await client.post(f"/properties/{w.prop_id}/units", json={"name": "X"}, headers=mh)
    ).status_code == 403
    assert (await client.get(f"/properties/{w.prop_id}/tariffs", headers=mh)).status_code == 403
    assert len((await client.get("/properties", headers=mh)).json()) == 1
    # ungrantable permission rejected
    r = await client.put(
        f"/properties/{w.prop_id}/managers",
        json={"email": "mgr@demo-mail.org", "full_name": "x", "permissions": ["payment.reverse"]},
        headers=w.oh,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_permission"
    # manager of nothing else
    other = await make_world(client, with_tenant=False)
    assert (await client.get(f"/properties/{other.prop_id}", headers=mh)).status_code == 403


async def test_cross_owner_and_tenant_isolation_on_crud(client):
    a = await make_world(client)
    b = await make_world(client)
    for method, url in [
        ("get", f"/properties/{b.prop_id}"),
        ("get", f"/properties/{b.prop_id}/units"),
        ("get", f"/properties/{b.prop_id}/tariffs"),
        ("get", f"/leases/{b.lease_id}"),
        ("get", f"/units/{b.unit_id}/meters"),
    ]:
        assert (await getattr(client, method)(url, headers=a.oh)).status_code == 403, url
        assert (await getattr(client, method)(url, headers=a.th)).status_code == 403, url
    # tenant of A sees only their own lease and cannot see properties
    assert [x["id"] for x in (await client.get("/leases", headers=a.th)).json()] == [a.lease_id]
    assert (await client.get("/properties", headers=a.th)).json() == []
    assert (await client.get(f"/properties/{a.prop_id}", headers=a.th)).status_code == 403
    # a stranger owner sees nothing
    s = await signup(client)
    assert (await client.get("/leases", headers=auth(s))).json() == []
