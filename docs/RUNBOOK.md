# Runbook
**Start (dev):** `docker compose up -d postgres redis minio`; `cd backend && uv run alembic upgrade head && uv run python -m app.seed`;
`uv run uvicorn app.main:app --port 8010`; `uv run arq app.worker.WorkerSettings`; `cd frontend && npm run build && npm start` → http://localhost:3010.
Demo logins (FAKE): `owner@demo.demo-mail.org` / `tenant1@demo.demo-mail.org`, password `demo-password-FAKE`.
**Stop:** Ctrl-C processes; `docker compose down` (add `-v` only to wipe data).
**Logs:** JSON lines on stdout, every line has `request_id` (also returned as `x-request-id`).
**Backup:** `scripts/backup.sh` (pg_dump + MinIO volume tarball, keeps 7). **Restore (tested):** `scripts/restore_pg.sh backups/pg-X.dump new_db_name` restores into a NEW database; verify, then switch `DATABASE_URL`.
**Rotate secrets:** change `JWT_SECRET` (logs everyone out), `LINK_SECRET` (invalidates open invite/Telegram links), restart api+worker.
**Re-run billing safely:** it is idempotent: `POST /leases/{id}/billing/run` or restart the worker (runs at startup). Existing periods are never duplicated.
**Common failures:** `/ready` 503 → see which of db/redis/storage failed; `billing_failed` notification → add the missing tariff, re-run billing; MinIO image pull errors → see DECISIONS D001.
