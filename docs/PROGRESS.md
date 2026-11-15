# PROGRESS

## CURRENT STATE / NEXT STEP
- All phases implemented locally; remaining: deploy (BLOCKERS 2–3).
- Infra running locally: `docker compose up -d postgres redis minio` (ports 5441/6391/9110). Test DB `rento_test` is created automatically by tests.
- Run checks: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`

## Log (append-only)
- 2026-11-15 Phase 0: env checked (docs/ENVIRONMENT.md). `minio/minio` not pullable (D001); `chainguard/minio` works (`/minio/health/live` → 200).
- 2026-11-15 Phase 0: backend skeleton; `pytest` 3 passed, ruff + mypy clean. Commit 61571b8.
- 2026-11-15 Phase 1: models, Alembic initial migration with btree_gist exclusion constraints (lease overlap, tariff overlap), append-only triggers, deferred invoice-total trigger. `alembic upgrade head → downgrade base → upgrade head` OK on fresh DB. Seed (FAKE data) idempotent. `pytest`: 13 passed; ruff + mypy clean.
- 2026-11-15 Phase 2: policy `can()` (mypy strict), JWT access + rotating refresh with reuse detection, invite links (itsdangerous, one-time via DB row), Redis rate limiter, audit helper. Note: `email-validator` rejects reserved domains (`.test`, `example.com`) → tests/seed use `demo-mail.org`. `pytest`: 100 passed; ruff + mypy clean.
- 2026-11-15 Phase 3: CRUD for properties/managers/units/leases(+invite)/meters/tariffs (history closes previous open tariff). `pytest` 107 passed at that point.
- 2026-11-15 Phase 4: readings (presigned POST upload, submit with key-prefix/type/size/date/monotonic checks, confirm/reject + notification outbox, owner baseline for new/replaced meter). Real MinIO integration test proves storage-side policy (size/content-type) enforcement. `pytest`: 116 passed.
- 2026-11-15 Phase 5: pure billing core (`app/billing/core.py`, `periods.py`, `allocation.py`, mypy strict) + hypothesis tests (total==sum(lines), periods tile lease, FIFO invariants, prorate bounds); DB service + idempotent job (per-lease transaction, row lock, unique (lease, period_start), 7-day catch-up) + ARQ worker (cron 00:10 Asia/Tashkent). Ran the real worker against Redis: `cron:daily_billing ● {'created': 0, ...}`. Migration 2 (adjustments, invoice number sequence, dropped total>=0 check) up/down OK. `pytest`: 152 passed.
- 2026-11-15 Phase 7: invoice/contract PDFs (WeasyPrint 70 + Jinja2; sandboxed owner template; URL fetching blocked; versioned documents in MinIO), Telegram transport behind `Notifier` (aiogram 3 bot with deep-link `/start <signed token>`, outbox delivery, scans for due/overdue/reading reminders). Backend support for the UI: `/dashboard`, `/audit` (scoped by `owner_id`, migration 3). `pytest`: 180 passed; ruff + mypy clean. Real Telegram API not exercised (BLOCKER 1).
- 2026-11-16 Phase 8–11: frontend `tsc`, `lint`, `build` pass; stack run locally (api :8010, worker, frontend :3010); smoke via frontend proxy: login → billing run (10 invoices) → invoice PDF (200, %PDF) → dashboard OK. Backup + restore into a new DB verified (10 invoices). Prod compose/Dockerfile/deploy.sh written but NOT built/executed (BLOCKERS 2–3). Docs written.
