import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# Point the whole app at the TEST database before anything imports settings.
_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://rento:rento@localhost:5441/rento_test"
)
os.environ["DATABASE_URL"] = _TEST_URL
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent


def _admin_url() -> str:
    return _TEST_URL.rsplit("/", 1)[0] + "/postgres"


@pytest.fixture(scope="session", autouse=True)
async def _migrated_db() -> AsyncIterator[None]:
    """Create a fresh test DB and migrate it with the real Alembic migrations."""
    name = _TEST_URL.rsplit("/", 1)[1]
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await c.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()
    env = {**os.environ, "ALEMBIC_DATABASE_URL": _TEST_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True
    )
    yield
    from app.db import dispose_engine

    await dispose_engine()


@pytest.fixture(autouse=True)
async def _clean_tables(_migrated_db: None) -> AsyncIterator[None]:
    yield
    from app.db import get_engine
    from app.services.ratelimit import get_redis

    r = get_redis()
    for k in await r.keys("rl:*"):
        await r.delete(k)
    async with get_engine().begin() as conn:
        names = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
        ).scalars()
        await conn.execute(text("TRUNCATE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    from app.db import get_sessionmaker

    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def storage():
    from tests.fakes import InMemoryStorage

    return InMemoryStorage()


@pytest.fixture
async def client(storage) -> AsyncIterator[AsyncClient]:
    from app.main import app
    from app.services.storage import get_storage

    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
