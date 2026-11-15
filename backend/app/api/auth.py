from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Session
from app.errors import Conflict, Unauthorized
from app.models.entities import Invite, Lease, User
from app.security import hash_password, verify_password
from app.services.audit import audit
from app.services.auth import (
    create_access_token,
    issue_refresh_token,
    read_invite_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.services.ratelimit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

Password = Field(min_length=8, max_length=128)


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Password
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Password
    phone: str | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    phone: str | None
    locale: str
    telegram_linked: bool


class InvitePreviewOut(BaseModel):
    email: str
    full_name: str
    unit_name: str


def user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        phone=u.phone,
        locale=u.locale,
        telegram_linked=u.telegram_chat_id is not None,
    )


async def _tokens(session: Session, user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user),
        refresh_token=await issue_refresh_token(session, user),
    )


@router.post(
    "/signup",
    response_model=TokenOut,
    status_code=201,
    dependencies=[Depends(rate_limit("signup", 10, 3600))],
)
async def signup(body: SignupIn, session: Session) -> TokenOut:
    """Public signup creates an *owner* account (tenants join via invite; managers via owner)."""
    exists = await session.scalar(
        select(User.id).where(func.lower(User.email) == body.email.lower())
    )
    if exists:
        raise Conflict("Email already registered", code="email_taken")
    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        phone=body.phone,
        role="owner",
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()
    await audit(
        session, user.id, "user.signup", "user", user.id, after={"role": "owner"}, owner_id=user.id
    )
    return await _tokens(session, user)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit("login", 10, 60))])
async def login(body: LoginIn, session: Session) -> TokenOut:
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if (
        user is None
        or not user.is_active
        or user.password_hash is None
        or not verify_password(user.password_hash, body.password)
    ):
        raise Unauthorized("Wrong email or password", code="bad_credentials")
    return await _tokens(session, user)


@router.post(
    "/refresh", response_model=TokenOut, dependencies=[Depends(rate_limit("refresh", 30, 60))]
)
async def refresh(body: RefreshIn, session: Session) -> TokenOut:
    user, new_refresh = await rotate_refresh_token(session, body.refresh_token)
    return TokenOut(access_token=create_access_token(user), refresh_token=new_refresh)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, session: Session) -> None:
    await revoke_refresh_token(session, body.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)


async def _load_invite(session: Session, token: str) -> Invite:
    invite_id = read_invite_token(token)
    invite = await session.get(Invite, invite_id)
    if invite is None:
        raise Unauthorized("Invalid invite link")
    if invite.accepted_at is not None:
        raise Unauthorized("Invite already used", code="invite_used")
    if invite.expires_at < datetime.now(UTC):
        raise Unauthorized("Invite link expired")
    return invite


@router.get(
    "/invite/{token}",
    response_model=InvitePreviewOut,
    dependencies=[Depends(rate_limit("invite", 20, 60))],
)
async def invite_preview(token: str, session: Session) -> InvitePreviewOut:
    invite = await _load_invite(session, token)
    lease = await session.get(Lease, invite.lease_id)
    assert lease is not None
    await session.refresh(lease, ["unit"])
    return InvitePreviewOut(
        email=invite.email, full_name=invite.full_name, unit_name=lease.unit.name
    )


@router.post(
    "/invite/accept", response_model=TokenOut, dependencies=[Depends(rate_limit("invite", 20, 60))]
)
async def invite_accept(body: AcceptInviteIn, session: Session) -> TokenOut:
    """One-time: creates the tenant account and attaches it to the lease."""
    invite = await _load_invite(session, body.token)
    if await session.scalar(select(User.id).where(func.lower(User.email) == invite.email.lower())):
        raise Conflict("An account with this email already exists", code="email_taken")
    user = User(
        email=invite.email.lower(),
        full_name=invite.full_name,
        phone=body.phone,
        role="tenant",
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()
    lease = await session.get(Lease, invite.lease_id)
    assert lease is not None
    lease.tenant_id = user.id
    invite.accepted_at = datetime.now(UTC)
    await audit(
        session,
        user.id,
        "invite.accept",
        "lease",
        lease.id,
        after={"tenant_id": str(user.id)},
        owner_id=await _lease_owner(session, lease),
    )
    return await _tokens(session, user)


class TelegramLinkOut(BaseModel):
    token: str
    url: str | None


@router.post("/telegram-link", response_model=TelegramLinkOut)
async def telegram_link(user: CurrentUser) -> TelegramLinkOut:
    """Signed, expiring deep link (t.me/<bot>?start=<token>) that binds a Telegram chat to this user.
    ``url`` is null until TELEGRAM_BOT_USERNAME is configured (see docs/BLOCKERS.md)."""
    from app.services.telegram import deep_link, make_link_token

    token = make_link_token(user.id)
    return TelegramLinkOut(token=token, url=deep_link(token))


async def _lease_owner(session: Session, lease: Lease) -> UUID:
    from app.models.entities import Property, Unit

    unit = await session.get(Unit, lease.unit_id)
    assert unit is not None
    prop = await session.get(Property, unit.property_id)
    assert prop is not None
    return prop.owner_id
