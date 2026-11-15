from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from app.models.entities import AuditLog


def _ctx_owner() -> UUID | None:
    raw = get_contextvars().get("owner_id")
    return UUID(raw) if raw else None


async def audit(
    session: AsyncSession,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: object,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    owner_id: UUID | None = None,
) -> None:
    """Record who/when/what-changed for every money-affecting (and security) action."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            owner_id=owner_id or _ctx_owner(),
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before=before,
            after=after,
            request_id=get_contextvars().get("request_id"),
        )
    )
