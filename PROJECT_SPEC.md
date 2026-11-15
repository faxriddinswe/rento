# PROJECT SPEC — "Rento" (condensed copy of the owner's autonomous spec)

Protocol: execute all phases end to end without asking; decide, document in docs/DECISIONS.md;
ask only for destructive actions / money / owner-only secrets / sudo / unknown remote hosts / real personal data.
Blocked ≠ stopped: fake implementation + docs/BLOCKERS.md entry. Docs: PROGRESS (CURRENT STATE/NEXT STEP), DECISIONS,
ARCHITECTURE (mermaid), BILLING_RULES, ENVIRONMENT, BLOCKERS, RUNBOOK, DEPLOY, uz/LEARN.md (Uzbek, 3+ interview Q&A per phase), README.
Language: code/docs English; UI Uzbek (Latin) with i18n (ru/en ready); LEARN.md + final report Uzbek.
Honesty: never claim unrun things work; verify library APIs; no real tariffs/legal facts (seed data FAKE; contract is a sample, not legal advice);
no weakened tests; no secrets in git. Phase done = tests pass, ruff+mypy clean, migrations up/down on fresh DB, compose boots, docs, commit.
Deployment: shared VPS, edge Caddy /opt/edge, deploy/rento.caddy, no published ports, mem limits ~1GB total, .env.deploy gitignored.

Stack: Python 3.12, FastAPI, Pydantic v2, PostgreSQL 16 (btree_gist), SQLAlchemy 2 async + asyncpg, Alembic, Redis+ARQ, MinIO presigned uploads,
WeasyPrint+Jinja2, aiogram 3, argon2, JWT access+refresh rotation, signed invite links. pytest/hypothesis on real PG; ruff; mypy strict in domain/billing core.
Frontend: Next.js App Router + TS + Tailwind + TanStack Query + OpenAPI types, mobile-first.
Roles: owner, manager (per-property perms), tenant; explicit can(user, action, resource) policy + permission-matrix test.
Entities: users, properties, units, leases (exclusion constraint), meters, meter_readings(pending|confirmed|rejected), tariffs(history, tiers),
invoices+lines, payments+allocations, append-only ledger_entries, documents, notifications(idempotent), audit_log.
Hard reqs: no floats; one rounding rule in one place; invoice total == sum(lines); append-only ledger w/ reversals; overpayment→credit; FIFO allocation;
idempotent daily ARQ billing (Asia/Tashkent, unique(lease_id,period)); utility lines from confirmed readings × tariff on reading date; documented mid-period tariff rule;
missing reading → pending line + adjustment later; prorated rent; lower reading rejected unless meter replaced; billing core pure.
Readings: presigned upload, key under tenant prefix, validate type/size, owner confirms/rejects. PDFs: contract (Jinja2 template), invoice.
Telegram notifications (interface + fake; bot token = BLOCKER). Security: tenant isolation tests, auth rate limiting, error format, request_id logs, /health /ready, audit log.
Phases: 0 skeleton; 1 data model+seed; 2 auth/RBAC; 3 CRUD; 4 readings; 5 billing; 6 payments/ledger; 7 PDFs+Telegram; 8 frontend; 9 hardening/backups; 10 deploy; 11 final pass.
Final report in Uzbek: per-phase results w/ real test counts, how to run, BLOCKERS, what to learn, limitations.
