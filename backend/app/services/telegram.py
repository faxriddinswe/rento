"""Telegram transport behind an interface, deep-link account linking, and outbox delivery."""

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import Unauthorized
from app.logging import get_logger
from app.models.entities import Notification, User
from app.services.pdf import fmt_money

LINK_MAX_AGE = 24 * 3600
MAX_ATTEMPTS = 5


class Notifier(Protocol):
    configured: bool

    async def send(self, chat_id: int, text: str) -> None: ...


class TelegramNotifier:
    """Real transport (aiogram 3). Needs TELEGRAM_BOT_TOKEN — see docs/BLOCKERS.md."""

    configured = True

    def __init__(self, token: str) -> None:
        from aiogram import Bot

        self._bot = Bot(token=token)

    async def send(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def close(self) -> None:
        await self._bot.session.close()


class DisabledNotifier:
    """Used when no bot token is configured: nothing is sent, notifications are marked skipped."""

    configured = False

    async def send(self, chat_id: int, text: str) -> None:  # pragma: no cover - never called
        raise RuntimeError("Telegram is not configured")


def get_notifier() -> Notifier:
    token = get_settings().telegram_bot_token
    return TelegramNotifier(token) if token else DisabledNotifier()


# ---- deep-link account linking -------------------------------------------------------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().link_secret, salt="telegram-link")


def make_link_token(user_id: UUID) -> str:
    return _serializer().dumps(str(user_id))


def deep_link(token: str) -> str | None:
    username = get_settings().telegram_bot_username
    return f"https://t.me/{username}?start={token}" if username else None


async def link_chat(session: AsyncSession, token: str, chat_id: int) -> User:
    """Attach a Telegram chat to the user that signed the token (used by the bot's /start handler)."""
    try:
        user_id = UUID(_serializer().loads(token, max_age=LINK_MAX_AGE))
    except SignatureExpired as exc:
        raise Unauthorized("Link expired, request a new one in the app") from exc
    except (BadSignature, ValueError) as exc:
        raise Unauthorized("Invalid link") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Unknown user")
    other = await session.scalar(
        select(User).where(User.telegram_chat_id == chat_id, User.id != user.id)
    )
    if other is not None:
        other.telegram_chat_id = None  # a chat belongs to one account
    user.telegram_chat_id = chat_id
    return user


# ---- message texts (Uzbek; i18n-ready: one function per locale) ------------------------------
def render_message(kind: str, p: dict[str, Any], locale: str = "uz") -> str:
    m = fmt_money
    texts: dict[str, str] = {
        "reading_reminder": f"📟 Hisoblagich ko'rsatkichi kerak: {p.get('unit', '')}. "
        "Iltimos, ilovada ko'rsatkich va rasmni yuboring.",
        "reading_reminder_upcoming": f"📟 Hisob-kitob kuni yaqin. {p.get('unit', '')} hisoblagich "
        "ko'rsatkichlarini ilovada yuboring.",
        "invoice_issued": f"🧾 Yangi hisob-faktura {p.get('number', '')}: {m(int(p.get('total', 0)))} so'm. "
        f"To'lov muddati: {p.get('due_date', '')}.",
        "due_tomorrow": f"⏰ {p.get('number', '')} hisob-fakturasi uchun to'lov muddati ertaga "
        f"({p.get('due_date', '')}). Qoldiq: {m(int(p.get('remaining', 0)))} so'm.",
        "overdue": f"❗ {p.get('number', '')} bo'yicha to'lov muddati {p.get('days', '')} kun oldin o'tgan. "
        f"Qoldiq: {m(int(p.get('remaining', 0)))} so'm.",
        "reading_rejected": f"❌ Ko'rsatkichingiz ({p.get('value', '')}, {p.get('date', '')}) rad etildi. "
        f"Sabab: {p.get('reason', '')}",
        "payment_received": f"✅ To'lov qabul qilindi: {m(int(p.get('amount', 0)))} so'm.",
        "reading_pending": f"📟 {p.get('unit', '')}: ko'rsatkich kelmadi, hisob-fakturada "
        "«kutilmoqda» deb belgilandi.",
        "billing_failed": f"⚠️ Hisob-faktura yaratilmadi: {p.get('reason', '')}",
    }
    return texts.get(kind, f"Rento: {kind}")


async def deliver_pending(
    session: AsyncSession, notifier: Notifier, limit: int = 50
) -> dict[str, int]:
    """Send queued notifications. Safe to run concurrently (SKIP LOCKED); each row is final-state once."""
    log = get_logger("telegram")
    stats = {"sent": 0, "skipped": 0, "failed": 0, "retry": 0}
    rows = (
        (
            await session.execute(
                select(Notification)
                .where(Notification.status == "pending")
                .order_by(Notification.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for n in rows:
        user = await session.get(User, n.user_id)
        if not notifier.configured:
            n.status, n.error = "skipped", "telegram not configured"
        elif user is None or user.telegram_chat_id is None:
            n.status, n.error = "skipped", "user has not linked Telegram"
        else:
            try:
                await notifier.send(
                    user.telegram_chat_id, render_message(n.kind, n.payload, user.locale)
                )
                n.status, n.sent_at, n.error = "sent", datetime.now(UTC), None
            except Exception as exc:
                n.attempts += 1
                n.error = repr(exc)[:500]
                n.status = "failed" if n.attempts >= MAX_ATTEMPTS else "pending"
                log.warning("notification_send_failed", id=str(n.id), attempts=n.attempts)
                stats["retry" if n.status == "pending" else "failed"] += 1
                continue
        stats["sent" if n.status == "sent" else "skipped"] += 1
    return stats
