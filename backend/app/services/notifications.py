"""Notification outbox. Rows are inserted idempotently (unique dedupe_key); the worker sends them."""

from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Notification


async def enqueue(
    session: AsyncSession, user_id: UUID, kind: str, dedupe_key: str, payload: dict[str, Any]
) -> bool:
    """Queue a notification once per ``dedupe_key``. Returns True if newly queued."""
    stmt = (
        insert(Notification)
        .values(user_id=user_id, kind=kind, dedupe_key=dedupe_key, payload=payload)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Notification.id)
    )
    return (await session.execute(stmt)).first() is not None
