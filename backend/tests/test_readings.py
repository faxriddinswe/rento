from tests.helpers import auth, baseline, make_meter, make_world, submit


async def test_full_reading_flow_confirm(client, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m)
    r = await submit(w, storage, m, "1100.5", "2026-02-01")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["photo_url"].startswith("http://fake-storage/")
    inbox = (await client.get("/readings", params={"status": "pending"}, headers=w.oh)).json()
    assert [x["id"] for x in inbox] == [body["id"]]
    c = await client.post(f"/readings/{body['id']}/confirm", json={}, headers=w.oh)
    assert c.status_code == 200 and c.json()["status"] == "confirmed"
    again = await client.post(f"/readings/{body['id']}/confirm", json={}, headers=w.oh)
    assert again.status_code == 409


async def test_reject_notifies_tenant_and_stores_reason(client, storage, session):
    from sqlalchemy import select

    from app.models.entities import Notification

    w = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m)
    rid = (await submit(w, storage, m, "1200", "2026-02-01")).json()["id"]
    r = await client.post(
        f"/readings/{rid}/reject", json={"reason": "photo is blurry"}, headers=w.oh
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    notes = (await session.execute(select(Notification))).scalars().all()
    assert len(notes) == 1 and notes[0].kind == "reading_rejected"
    assert notes[0].payload["reason"] == "photo is blurry"
    # tenant sees the rejection reason in their list
    mine = (await client.get("/readings", headers=w.th)).json()
    assert mine[0]["reject_reason"] == "photo is blurry"


async def test_lower_reading_rejected_unless_baseline(client, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m, "1000")
    r = await submit(w, storage, m, "900", "2026-02-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "reading_lower_than_previous"
    # owner records meter replacement as a new baseline; then small values are fine
    await baseline(w, m, "5", "2026-02-01", replaced_final_value="1050")
    r = await submit(w, storage, m, "20", "2026-03-01")
    assert r.status_code == 201


async def test_tenant_cannot_use_foreign_photo_key_or_missing_photo(client, storage):
    w = await make_world(client)
    other = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m)
    # key under another tenant's prefix
    om = await make_meter(other)
    up = await client.post(
        f"/meters/{om}/photo-upload",
        json={"content_type": "image/png", "size": 5},
        headers=other.th,
    )
    foreign_key = up.json()["key"]
    await storage.put(foreign_key, b"x", "image/png")
    r = await client.post(
        f"/meters/{m}/readings",
        headers=w.th,
        json={"value": "1100", "reading_date": "2026-02-01", "photo_key": foreign_key},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "photo_key_forbidden"
    # key under own prefix but nothing uploaded
    own = (
        await client.post(
            f"/meters/{m}/photo-upload", json={"content_type": "image/png", "size": 5}, headers=w.th
        )
    ).json()["key"]
    r = await client.post(
        f"/meters/{m}/readings",
        headers=w.th,
        json={"value": "1100", "reading_date": "2026-02-01", "photo_key": own},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "photo_missing"
    # wrong stored content type
    await storage.put(own, b"x", "text/html")
    r = await client.post(
        f"/meters/{m}/readings",
        headers=w.th,
        json={"value": "1100", "reading_date": "2026-02-01", "photo_key": own},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "photo_type"


async def test_photo_upload_validation(client, storage):
    w = await make_world(client)
    m = await make_meter(w)
    r = await client.post(
        f"/meters/{m}/photo-upload", json={"content_type": "image/gif", "size": 5}, headers=w.th
    )
    assert r.status_code == 422
    r = await client.post(
        f"/meters/{m}/photo-upload",
        json={"content_type": "image/png", "size": 50_000_000},
        headers=w.th,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "photo_too_large"


async def test_date_rules_and_duplicates(client, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m)
    assert (await submit(w, storage, m, "1010", "2999-01-01")).json()["error"][
        "code"
    ] == "reading_future"
    assert (await submit(w, storage, m, "1010", "2025-12-01")).json()["error"][
        "code"
    ] == "reading_outside_lease"
    assert (await submit(w, storage, m, "1010", "2026-02-01")).status_code == 201
    assert (await submit(w, storage, m, "1020", "2026-02-01")).json()["error"][
        "code"
    ] == "reading_duplicate"


async def test_higher_than_later_confirmed_rejected(client, storage):
    w = await make_world(client)
    m = await make_meter(w)
    await baseline(w, m)
    await submit(w, storage, m, "1200", "2026-03-01", confirm=True)
    r = await submit(w, storage, m, "1300", "2026-02-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "reading_higher_than_next"
    assert (await submit(w, storage, m, "1100", "2026-02-01")).status_code == 201


async def test_tenant_isolation_on_readings(client, storage):
    a = await make_world(client)
    b = await make_world(client)
    am, bm = await make_meter(a), await make_meter(b)
    await baseline(a, am)
    await baseline(b, bm)
    rid = (await submit(b, storage, bm, "1100", "2026-02-01")).json()["id"]
    # A's tenant cannot submit on B's meter, nor see/review B's readings
    up = await client.post(
        f"/meters/{bm}/photo-upload", json={"content_type": "image/png", "size": 5}, headers=a.th
    )
    assert up.status_code == 403
    for h in (a.th, a.oh):
        assert rid not in [x["id"] for x in (await client.get("/readings", headers=h)).json()]
    assert (await client.post(f"/readings/{rid}/confirm", json={}, headers=a.th)).status_code == 403
    assert (await client.post(f"/readings/{rid}/confirm", json={}, headers=a.oh)).status_code == 403
    assert (
        await client.post(f"/readings/{rid}/reject", json={"reason": "x"}, headers=a.th)
    ).status_code == 403
    # B's tenant cannot review own reading
    assert (await client.post(f"/readings/{rid}/confirm", json={}, headers=b.th)).status_code == 403
    # manager with reading.review on A cannot touch B
    await client.put(
        f"/properties/{a.prop_id}/managers",
        headers=a.oh,
        json={
            "email": "m@demo-mail.org",
            "full_name": "M",
            "password": "manager-pass-1",
            "permissions": ["reading.review", "reading.read"],
        },
    )
    tok = (
        await client.post(
            "/auth/login", json={"email": "m@demo-mail.org", "password": "manager-pass-1"}
        )
    ).json()
    assert (
        await client.post(f"/readings/{rid}/confirm", json={}, headers=auth(tok))
    ).status_code == 403
