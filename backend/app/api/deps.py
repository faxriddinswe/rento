import uuid
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.policies import Action, Actor, Resource, can
from app.errors import Forbidden, Unauthorized
from app.models.entities import PropertyManager, User
from app.services.auth import decode_access_token
from app.services.storage import Storage, get_storage

Session = Annotated[AsyncSession, Depends(get_session)]


async def current_user(request: Request, session: Session) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token")
    user_id = decode_access_token(token)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User not found or disabled")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def load_actor(session: AsyncSession, user: User) -> Actor:
    managed: dict[uuid.UUID, frozenset[str]] = {}
    if user.role == "manager":
        rows = await session.execute(
            select(PropertyManager).where(PropertyManager.user_id == user.id)
        )
        managed = {r.property_id: frozenset(r.permissions) for r in rows.scalars()}
    return Actor(id=user.id, role=user.role, managed=managed)


async def current_actor(session: Session, user: CurrentUser) -> Actor:
    return await load_actor(session, user)


CurrentActor = Annotated[Actor, Depends(current_actor)]


def authorize(actor: Actor, action: Action, resource: Resource | None = None) -> None:
    """Raise 403 unless the policy allows it."""
    if not can(actor, action, resource):
        raise Forbidden(f"Not allowed: {action.value}")
    # remember whose data this request touches so audit rows can be scoped per owner
    owner = (
        resource.owner_id
        if resource and resource.owner_id
        else (actor.id if actor.role == "owner" else None)
    )
    if owner:
        structlog.contextvars.bind_contextvars(owner_id=str(owner))


StorageDep = Annotated[Storage, Depends(get_storage)]
