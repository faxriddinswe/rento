import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.entities import AuditLog, Invite, Lease, Property, Unit, User
from app.services.auth import sign_invite

SIGNUP = {"email": "Owner@demo-mail.org", "password": "correct-horse-1", "full_name": "FAKE Owner"}


async def _signup(client, **over):
    r = await client.post("/auth/signup", json={**SIGNUP, **over})
    assert r.status_code == 201, r.text
    return r.json()


def _h(tok):
    return {"authorization": f"Bearer {tok['access_token']}"}


async def test_signup_login_me(client):
    tok = await _signup(client)
    me = await client.get("/auth/me", headers=_h(tok))
    assert me.status_code == 200 and me.json()["role"] == "owner"
    assert me.json()["email"] == "owner@demo-mail.org"
    r = await client.post(
        "/auth/login", json={"email": "OWNER@demo-mail.org", "password": SIGNUP["password"]}
    )
    assert r.status_code == 200


async def test_duplicate_email_and_bad_credentials(client):
    await _signup(client)
    r = await client.post("/auth/signup", json={**SIGNUP, "email": "owner@demo-mail.org"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = await client.post(
        "/auth/login", json={"email": SIGNUP["email"], "password": "wrong-password"}
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"


async def test_me_requires_valid_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (
        await client.get("/auth/me", headers={"authorization": "Bearer junk"})
    ).status_code == 401


async def test_validation_error_format(client):
    r = await client.post("/auth/signup", json={"email": "x", "password": "short"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and err["details"] and err["request_id"]


async def test_refresh_rotation_and_reuse_detection(client):
    tok = await _signup(client)
    r1 = await client.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refresh_token"] != tok["refresh_token"]
    # replaying the OLD token = theft signal: rejected and whole family revoked
    replay = await client.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert replay.status_code == 401
    after = await client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert after.status_code == 401


async def test_logout_revokes_refresh(client):
    tok = await _signup(client)
    assert (
        await client.post("/auth/logout", json={"refresh_token": tok["refresh_token"]})
    ).status_code == 204
    r = await client.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401


async def test_login_rate_limited(client):
    codes = [
        (
            await client.post(
                "/auth/login", json={"email": "a@demo-mail.org", "password": "xxxxxxxx"}
            )
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


async def _lease_with_invite(session, email="t@demo-mail.org", expires=None, owner="o"):
    owner = User(email=f"{owner}@demo-mail.org", full_name="O", role="owner")
    session.add(owner)
    await session.flush()
    prop = Property(owner_id=owner.id, name="P")
    session.add(prop)
    await session.flush()
    unit = Unit(property_id=prop.id, name="Apt 7")
    session.add(unit)
    await session.flush()
    lease = Lease(unit_id=unit.id, start_date=datetime.now(UTC).date(), monthly_rent=1)
    session.add(lease)
    await session.flush()
    inv = Invite(
        lease_id=lease.id,
        email=email,
        full_name="FAKE Tenant",
        expires_at=expires or datetime.now(UTC) + timedelta(days=7),
    )
    session.add(inv)
    await session.commit()
    return lease.id, inv.id


async def test_invite_accept_is_one_time(client, session):
    lease_id, inv_id = await _lease_with_invite(session)
    token = sign_invite(inv_id)
    pv = await client.get(f"/auth/invite/{token}")
    assert pv.status_code == 200 and pv.json()["unit_name"] == "Apt 7"
    r = await client.post("/auth/invite/accept", json={"token": token, "password": "tenant-pass-1"})
    assert r.status_code == 200
    me = await client.get("/auth/me", headers=_h(r.json()))
    assert me.json()["role"] == "tenant"
    lease = await session.get(Lease, lease_id)
    await session.refresh(lease)
    assert lease.tenant_id is not None
    again = await client.post(
        "/auth/invite/accept", json={"token": token, "password": "tenant-pass-1"}
    )
    assert again.status_code == 401 and again.json()["error"]["code"] == "invite_used"


async def test_invite_tampered_or_expired_rejected(client, session):
    _, inv_id = await _lease_with_invite(session)
    token = sign_invite(inv_id)
    bad = await client.post(
        "/auth/invite/accept", json={"token": token + "x", "password": "tenant-pass-1"}
    )
    assert bad.status_code == 401
    random_id = sign_invite(uuid.uuid4())
    assert (await client.get(f"/auth/invite/{random_id}")).status_code == 401
    _, expired_id = await _lease_with_invite(
        session, email="e@demo-mail.org", expires=datetime.now(UTC) - timedelta(days=1), owner="o2"
    )
    r = await client.post(
        "/auth/invite/accept", json={"token": sign_invite(expired_id), "password": "tenant-pass-1"}
    )
    assert r.status_code == 401


async def test_security_actions_are_audited(client, session):
    await _signup(client)
    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert [r.action for r in rows] == ["user.signup"]
    assert rows[0].request_id
