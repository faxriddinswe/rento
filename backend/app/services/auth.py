"""Tokens and sessions: JWT access + rotating opaque refresh tokens with reuse detection."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import Unauthorized
from app.models.entities import RefreshToken, User

ALGO = "HS256"
INVITE_MAX_AGE = 7 * 24 * 3600


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(user: User) -> str:
    s = get_settings()
    now = _now()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGO)


def decode_access_token(token: str) -> uuid.UUID:
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired token") from exc
    if data.get("type") != "access":
        raise Unauthorized("Invalid token type")
    return uuid.UUID(data["sub"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_refresh_token(
    session: AsyncSession, user: User, family_id: uuid.UUID | None = None
) -> str:
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=_hash(raw),
            expires_at=_now() + timedelta(days=get_settings().refresh_token_days),
        )
    )
    await session.flush()
    return raw


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[User, str]:
    """Exchange a refresh token for a new one. Re-use of a rotated token revokes the whole family."""
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    ).scalar_one_or_none()
    if row is None:
        raise Unauthorized("Invalid refresh token")
    if row.revoked_at is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await session.commit()  # persist the revocation even though we raise
        raise Unauthorized("Refresh token reuse detected; please sign in again")
    if row.expires_at < _now():
        raise Unauthorized("Refresh token expired")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User disabled")
    row.revoked_at = _now()
    new_raw = await issue_refresh_token(session, user, row.family_id)
    return user, new_raw


async def revoke_refresh_token(session: AsyncSession, raw: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def _invite_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().link_secret, salt="tenant-invite")


def sign_invite(invite_id: uuid.UUID) -> str:
    return _invite_serializer().dumps(str(invite_id))


def read_invite_token(token: str) -> uuid.UUID:
    try:
        return uuid.UUID(_invite_serializer().loads(token, max_age=INVITE_MAX_AGE))
    except SignatureExpired as exc:
        raise Unauthorized("Invite link expired") from exc
    except (BadSignature, ValueError) as exc:
        raise Unauthorized("Invalid invite link") from exc
