"""API-level test helpers: build a small world through the real endpoints."""

from dataclasses import dataclass, field
from itertools import count

_n = count(1)


def auth(tok: dict) -> dict:
    return {"authorization": f"Bearer {tok['access_token']}"}


async def signup(client, label="owner") -> dict:
    n = next(_n)
    r = await client.post(
        "/auth/signup",
        json={
            "email": f"{label}{n}@demo-mail.org",
            "password": "correct-horse-1",
            "full_name": f"FAKE {label} {n}",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@dataclass
class World:
    client: object
    owner: dict = field(default_factory=dict)
    prop_id: str = ""
    unit_id: str = ""
    lease_id: str = ""
    tenant: dict = field(default_factory=dict)
    tenant_email: str = ""

    @property
    def oh(self) -> dict:
        return auth(self.owner)

    @property
    def th(self) -> dict:
        return auth(self.tenant)


async def make_world(client, *, start="2026-01-01", rent=300_000_000, with_tenant=True) -> World:
    w = World(client)
    w.owner = await signup(client, "owner")
    r = await client.post("/properties", json={"name": "FAKE House"}, headers=w.oh)
    w.prop_id = r.json()["id"]
    r = await client.post(f"/properties/{w.prop_id}/units", json={"name": "Apt 1"}, headers=w.oh)
    w.unit_id = r.json()["id"]
    r = await client.post(
        f"/units/{w.unit_id}/leases",
        json={"start_date": start, "monthly_rent": rent, "billing_day": 1},
        headers=w.oh,
    )
    assert r.status_code == 201, r.text
    w.lease_id = r.json()["id"]
    if with_tenant:
        await add_tenant(w)
    return w


async def add_tenant(w: World) -> None:
    client = w.client
    n = next(_n)
    w.tenant_email = f"tenant{n}@demo-mail.org"
    r = await client.post(
        f"/leases/{w.lease_id}/invite",
        json={"email": w.tenant_email, "full_name": "FAKE Tenant"},
        headers=w.oh,
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/auth/invite/accept", json={"token": r.json()["token"], "password": "tenant-pass-1"}
    )
    assert r.status_code == 200, r.text
    w.tenant = r.json()


async def make_meter(w: World, kind="electricity") -> str:
    r = await w.client.post(
        f"/units/{w.unit_id}/meters", json={"kind": kind, "unit_label": "kWh"}, headers=w.oh
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def baseline(w: World, meter_id: str, value="1000", date="2026-01-01", **extra) -> dict:
    r = await w.client.post(
        f"/meters/{meter_id}/baseline",
        json={"value": value, "reading_date": date, **extra},
        headers=w.oh,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def submit(w: World, storage, meter_id: str, value, date, *, confirm=False) -> dict:
    """Tenant uploads a (fake) photo and submits a reading. Returns the response JSON."""
    c = w.client
    up = await c.post(
        f"/meters/{meter_id}/photo-upload",
        json={"content_type": "image/jpeg", "size": 10},
        headers=w.th,
    )
    assert up.status_code == 200, up.text
    key = up.json()["key"]
    await storage.put(key, b"\xff\xd8photo", "image/jpeg")
    r = await c.post(
        f"/meters/{meter_id}/readings",
        json={"value": str(value), "reading_date": date, "photo_key": key},
        headers=w.th,
    )
    if confirm:
        assert r.status_code == 201, r.text
        r = await c.post(f"/readings/{r.json()['id']}/confirm", json={}, headers=w.oh)
        assert r.status_code == 200, r.text
    return r
