# PROGRESS

## CURRENT STATE / NEXT STEP
- Phases 0–2 done (commit per phase). **NEXT: Phase 3 — CRUD for properties, units, leases, meters, tariffs (with history)**.
- Infra running locally: `docker compose up -d postgres redis minio` (ports 5441/6391/9110). Test DB `rento_test` is created automatically by tests.
- Run checks: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`

## Log (append-only)
- 2026-11-15 Phase 0: env checked (docs/ENVIRONMENT.md). `minio/minio` not pullable (D001); `chainguard/minio` works (`/minio/health/live` → 200).
- 2026-11-15 Phase 0: backend skeleton; `pytest` 3 passed, ruff + mypy clean. Commit 61571b8.
- 2026-11-15 Phase 1: models, Alembic initial migration with btree_gist exclusion constraints (lease overlap, tariff overlap), append-only triggers, deferred invoice-total trigger. `alembic upgrade head → downgrade base → upgrade head` OK on fresh DB. Seed (FAKE data) idempotent. `pytest`: 13 passed; ruff + mypy clean.
- 2026-11-15 Phase 2: policy `can()` (mypy strict), JWT access + rotating refresh with reuse detection, invite links (itsdangerous, one-time via DB row), Redis rate limiter, audit helper. Note: `email-validator` rejects reserved domains (`.test`, `example.com`) → tests/seed use `demo-mail.org`. `pytest`: 100 passed; ruff + mypy clean.
