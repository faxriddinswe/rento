# Environment (recorded 2026-11-15)

| Tool | Version |
|---|---|
| OS | Linux 7.0.0-43-generic (Ubuntu) x86_64 |
| git | 2.53.0 |
| System Python | 3.14.4 (project uses uv-managed **3.12.16**) |
| uv | 0.13.8 |
| Node / npm | v26.13.1 / 11.20.0 |
| pnpm | 12.18.0 |
| Docker / Compose | 29.9.3 / v5.7.1 |
| psql / pg_dump | system client |

Backend deps are pinned by `backend/uv.lock` (key: fastapi 0.163.0, pydantic 2.13.5,
SQLAlchemy 2.1.8, asyncpg 0.32.0, alembic 1.20.1, arq 0.28.0, boto3 1.44.3,
weasyprint 70.0, aiogram 3.31.0, argon2-cffi 25.1.0, hypothesis 6.170.15, ruff 0.17.5, mypy 2.4.1).

Dev host ports (chosen to avoid other projects on this machine): postgres 5441, redis 6391,
minio API 9110 / console 9111, api 8010, frontend 3010.
