# PROGRESS

## CURRENT STATE / NEXT STEP
- Phases 0–1 done (commit per phase). **NEXT: Phase 2 — Auth & RBAC** (JWT access+refresh rotation, owner signup, invite links, `can()` policy + permission-matrix test, auth rate limiting, audit helper).
- Infra running locally: `docker compose up -d postgres redis minio` (ports 5441/6391/9110). Test DB `rento_test` is created automatically by tests.
- Run checks: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`

## Log (append-only)
- 2026-11-15 Phase 0: env checked (docs/ENVIRONMENT.md). `minio/minio` not pullable (D001); `chainguard/minio` works (`/minio/health/live` → 200).
- 2026-11-15 Phase 0: backend skeleton; `pytest` 3 passed, ruff + mypy clean. Commit 61571b8.
- 2026-11-15 Phase 1: models, Alembic initial migration with btree_gist exclusion constraints (lease overlap, tariff overlap), append-only triggers, deferred invoice-total trigger. `alembic upgrade head → downgrade base → upgrade head` OK on fresh DB. Seed (FAKE data) idempotent. `pytest`: 13 passed; ruff + mypy clean.
