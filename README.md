# Rento — rental property & utility billing manager
Owners manage properties, leases, meters and tariffs; tenants send meter readings with photos; monthly invoices are generated automatically and correctly; everyone sees a transparent balance. UI is Uzbek (ru/en scaffold).

## Run it (dev)
```
docker compose up -d postgres redis minio
cd backend && uv sync && uv run alembic upgrade head && uv run python -m app.seed
uv run uvicorn app.main:app --port 8010 &  uv run arq app.worker.WorkerSettings &
cd ../frontend && npm ci && npm run build && npm start   # http://localhost:3010
```
Demo (FAKE) logins: `owner@demo.demo-mail.org`, `tenant1@demo.demo-mail.org` / `demo-password-FAKE`.
Tests: `cd backend && uv run pytest -q` (real PostgreSQL + MinIO from compose), `uv run ruff check . && uv run mypy app`; frontend: `npm run lint && npm run typecheck && npm run build`.

## Architecture
See `docs/ARCHITECTURE.md` (Mermaid components + ER). FastAPI + SQLAlchemy async + PostgreSQL 16, Redis/ARQ, MinIO (presigned POST), WeasyPrint, aiogram, Next.js.

## Design decisions (details in `docs/DECISIONS.md`)
Money = BIGINT tiyin, one half-up rounding per line; append-only ledger with reversing entries (DB triggers); idempotent billing (unique lease+period, row lock, 7-day catch-up); tariff history with exclusion constraints, priced at the later reading's date; presigned POST with size/type policy; RBAC as one pure `can()` function with a permission-matrix test.
Billing rules in plain language: `docs/BILLING_RULES.md`.

## Limitations
No real payment gateway (Click/Payme would be implemented from their official docs). Telegram needs a bot token (BLOCKERS). Not deployed. Tariffs are user-entered; seed data is FAKE. **The contract template is a sample, not legal advice.**
