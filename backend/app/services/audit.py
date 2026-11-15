from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from app.models.entities import AuditLog


async def audit(
    session: AsyncSession,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: object,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Record who/when/what-changed for every money-affecting (and security) action."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before=before,
            after=after,
            request_id=get_contextvars().get("request_id"),
        )
    )
