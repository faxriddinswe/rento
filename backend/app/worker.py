"""ARQ worker: daily billing cron (Asia/Tashkent). Run: arq app.worker.WorkerSettings"""

from typing import Any
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings

from app.billing.job import run_billing
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging import configure_logging
from app.notify_jobs import scan_notifications
from app.services.clock import today_local
from app.services.telegram import deliver_pending, get_notifier


async def daily_billing(ctx: dict[str, Any]) -> dict[str, int]:
    summary = await run_billing(get_sessionmaker(), today_local())
    return {
        "created": summary.created,
        "exists": summary.exists,
        "failed": summary.failed,
        "missing_tariff": summary.missing_tariff,
    }


async def queue_notifications(ctx: dict[str, Any]) -> dict[str, int]:
    return await scan_notifications(get_sessionmaker(), today_local())


async def send_notifications(ctx: dict[str, Any]) -> dict[str, int]:
    async with get_sessionmaker()() as session:
        stats = await deliver_pending(session, ctx["notifier"])
        await session.commit()
        return stats


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    ctx["notifier"] = get_notifier()


async def shutdown(ctx: dict[str, Any]) -> None:
    close = getattr(ctx["notifier"], "close", None)
    if close is not None:
        await close()


class WorkerSettings:
    functions = [daily_billing, queue_notifications, send_notifications]
    # 00:10 Asia/Tashkent daily; also once at startup (idempotent) so a restart never skips a day.
    cron_jobs = [
        cron(daily_billing, hour=0, minute=10, run_at_startup=True),
        cron(
            queue_notifications, hour=9, minute=0
        ),  # 09:00 Tashkent: due/overdue/reading reminders
        cron(send_notifications, second=0),  # every minute: deliver the outbox
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    timezone = ZoneInfo(get_settings().timezone)
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 1
