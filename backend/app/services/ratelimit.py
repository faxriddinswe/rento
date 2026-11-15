"""Fixed-window rate limiting in Redis, used on auth endpoints."""

from fastapi import Request
from redis.asyncio import Redis

from app.config import get_settings
from app.errors import RateLimited

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def reset_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


def rate_limit(name: str, limit: int, window_seconds: int):  # type: ignore[no-untyped-def]
    async def dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"rl:{name}:{ip}"
        r = get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_seconds)
        if count > limit:
            raise RateLimited("Too many requests, try again later")

    return dep
