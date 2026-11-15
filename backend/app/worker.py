"""ARQ worker: daily billing cron (Asia/Tashkent). Run: arq app.worker.WorkerSettings"""

from typing import Any
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings

from app.billing.job import run_billing
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging import configure_logging
from app.services.clock import today_local


async def daily_billing(ctx: dict[str, Any]) -> dict[str, int]:
    summary = await run_billing(get_sessionmaker(), today_local())
    return {
        "created": summary.created,
        "exists": summary.exists,
        "failed": summary.failed,
        "missing_tariff": summary.missing_tariff,
    }


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()


class WorkerSettings:
    functions = [daily_billing]
    # 00:10 Asia/Tashkent daily; also once at startup (idempotent) so a restart never skips a day.
    cron_jobs = [cron(daily_billing, hour=0, minute=10, run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    timezone = ZoneInfo(get_settings().timezone)
    on_startup = startup
    max_tries = 1
