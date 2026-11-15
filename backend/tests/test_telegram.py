from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.errors import Unauthorized
from app.models.entities import Notification, User
from app.notify_jobs import scan_notifications
from app.services.notifications import enqueue
from app.services.telegram import (
    DisabledNotifier,
    deliver_pending,
    link_chat,
    render_message,
)
from tests.helpers import make_world


class FakeNotifier:
    configured = True

    def __init__(self, fail=0):
        self.sent, self.fail = [], fail

    async def send(self, chat_id, text):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))


async def _tenant(session, w):
    return (
        await session.execute(
            select(User).where(User.role == "tenant", User.email == w.tenant_email)
        )
    ).scalar_one()


async def test_link_flow_via_api_and_handler(client, session):
    w = await make_world(client)
    r = await client.post("/auth/telegram-link", headers=w.th)
    assert r.status_code == 200 and r.json()["token"]
    token = r.json()["token"]
    async with get_sessionmaker()() as s:
        await link_chat(s, token, 777)
        await s.commit()
    u = await _tenant(session, w)
    assert u.telegram_chat_id == 777
    assert (await client.get("/auth/me", headers=w.th)).json()["telegram_linked"] is True
    # tampered / garbage tokens
    async with get_sessionmaker()() as s:
        for bad in (token + "x", "garbage"):
            with pytest.raises(Unauthorized):
                await link_chat(s, bad, 1)
    assert (await client.post("/auth/telegram-link")).status_code == 401


async def test_aiogram_start_handler(client, session):
    from app.telegram_bot import on_start

    w = await make_world(client)
    token = (await client.post("/auth/telegram-link", headers=w.th)).json()["token"]
    replies = []

    class Msg:
        chat = SimpleNamespace(id=4242)

        async def answer(self, text):
            replies.append(text)

    await on_start(Msg(), SimpleNamespace(args=token))
    await on_start(Msg(), SimpleNamespace(args="bad-token"))
    await on_start(Msg(), SimpleNamespace(args=None))
    assert "ulandi" in replies[0] and "Ulab bo'lmadi" in replies[1] and "Salom" in replies[2]
    assert (await _tenant(session, w)).telegram_chat_id == 4242


async def test_enqueue_is_idempotent(client, session):
    w = await make_world(client)
    uid = (await _tenant(session, w)).id
    assert await enqueue(session, uid, "invoice_issued", "k1", {}) is True
    assert await enqueue(session, uid, "invoice_issued", "k1", {}) is False
    await session.commit()


async def test_delivery_sent_skipped_retry_failed(client, session):
    w = await make_world(client)
    u = await _tenant(session, w)
    uid = u.id
    u.telegram_chat_id = 99
    await session.commit()
    await enqueue(session, uid, "payment_received", "p1", {"amount": 150000})
    await session.commit()
    n = FakeNotifier()
    stats = await deliver_pending(session, n)
    await session.commit()
    assert stats["sent"] == 1 and n.sent[0][0] == 99 and "1 500" in n.sent[0][1]
    assert (await deliver_pending(session, n))["sent"] == 0  # not re-sent
    # failing transport: retried up to MAX_ATTEMPTS then failed
    await enqueue(session, uid, "invoice_issued", "p2", {"number": "INV-1", "total": 100})
    await session.commit()
    bad = FakeNotifier(fail=99)
    for i in range(5):
        st = await deliver_pending(session, bad)
        await session.commit()
        assert st["retry"] == (1 if i < 4 else 0) and st["failed"] == (1 if i == 4 else 0)
    row = (
        await session.execute(select(Notification).where(Notification.dedupe_key == "p2"))
    ).scalar_one()
    assert row.status == "failed" and row.attempts == 5


async def test_unlinked_user_and_unconfigured_bot_are_skipped(client, session):
    w = await make_world(client)
    uid = (await _tenant(session, w)).id
    await enqueue(session, uid, "payment_received", "s1", {"amount": 1})
    await session.commit()
    assert (await deliver_pending(session, FakeNotifier()))["skipped"] == 1
    await enqueue(session, uid, "payment_received", "s2", {"amount": 1})
    await session.commit()
    assert (await deliver_pending(session, DisabledNotifier()))["skipped"] == 1
    rows = (await session.execute(select(Notification))).scalars().all()
    assert {r.status for r in rows} == {"skipped"}


def test_every_kind_renders_in_uzbek():
    for kind in (
        "reading_reminder",
        "reading_reminder_upcoming",
        "invoice_issued",
        "due_tomorrow",
        "overdue",
        "reading_rejected",
        "payment_received",
        "reading_pending",
        "billing_failed",
    ):
        assert len(render_message(kind, {})) > 10


async def test_scans_due_tomorrow_overdue_throttle_and_reading_reminder(client, session):
    w = await make_world(client)
    await client.post(
        f"/leases/{w.lease_id}/billing/run", json={"through": "2026-01-02"}, headers=w.oh
    )
    maker = get_sessionmaker()  # invoice due 2026-01-11
    r = await scan_notifications(maker, date(2026, 1, 10))
    assert r["due_tomorrow"] == 1
    assert (await scan_notifications(maker, date(2026, 1, 10)))["due_tomorrow"] == 0  # idempotent
    # overdue: throttled to one per 3-day bucket
    assert (await scan_notifications(maker, date(2026, 1, 12)))["overdue"] == 1
    assert (await scan_notifications(maker, date(2026, 1, 13)))["overdue"] == 0
    assert (await scan_notifications(maker, date(2026, 1, 14)))["overdue"] == 1
    # reading reminder 2 days before next billing day (Feb 1)
    assert (await scan_notifications(maker, date(2026, 1, 30)))["reading_reminder_upcoming"] == 1
    assert (await scan_notifications(maker, date(2026, 1, 30)))["reading_reminder_upcoming"] == 0
    # paying the invoice stops reminders
    await client.post(
        f"/leases/{w.lease_id}/payments",
        headers=w.oh,
        json={"amount": 300_000_000, "paid_on": "2026-01-14"},
    )
    assert (await scan_notifications(maker, date(2026, 2, 20)))["overdue"] == 0
