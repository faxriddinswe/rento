import os
import subprocess
import sys

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.entities import Lease, User
from app.seed import seed
from tests.conftest import BACKEND, _admin_url

FRESH = "rento_migrate_check"


async def test_migrations_apply_and_roll_back_on_fresh_db():
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'DROP DATABASE IF EXISTS "{FRESH}" WITH (FORCE)'))
        await c.execute(text(f'CREATE DATABASE "{FRESH}"'))
    url = _admin_url().rsplit("/", 1)[0] + f"/{FRESH}"
    env = {**os.environ, "ALEMBIC_DATABASE_URL": url}
    for step in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run([sys.executable, "-m", "alembic", *step], cwd=BACKEND, env=env, check=True)
    async with admin.connect() as c:
        await c.execute(text(f'DROP DATABASE "{FRESH}" WITH (FORCE)'))
    await admin.dispose()


async def test_seed_is_idempotent(session):
    assert await seed() is True
    assert await seed() is False
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 4
    assert (await session.execute(select(func.count()).select_from(Lease))).scalar_one() == 2
