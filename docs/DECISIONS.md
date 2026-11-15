# Decision records

## D001 — MinIO image source
- **Context:** `minio/minio` on Docker Hub no longer exists and `quay.io/minio/minio` returns 401 (MinIO stopped publishing community images).
- **Options:** build MinIO from source; use another S3 server (Garage/SeaweedFS); use the Chainguard build of MinIO (`chainguard/minio`, public on Docker Hub).
- **Decision:** `chainguard/minio:latest` (MinIO built from the official source by Chainguard, distroless, runs as uid 65532). Pin by digest before production deploy.
- **Consequences:** image has no shell/curl, so no in-container healthcheck; the API's `/ready` checks storage instead and creates the bucket on startup. Storage is behind a `Storage` interface so another S3 server can be swapped in via env.

## D002 — Dev ports
Host ports 5441/6391/9110/9111/8010/3010 because 5455/6380/6390 etc. are used by other projects on this machine.

## D003 — Money representation
- **Context:** Uzbek so'm has 100 tiyin; floats are forbidden.
- **Options:** NUMERIC(18,2) everywhere; BIGINT minor units; Decimal in Python only.
- **Decision:** All stored *amounts* (rent, line amount, invoice total, payments, ledger) are **BIGINT minor units (tiyin)**; Python uses `int`. Unit *prices* (per kWh/m³) are `NUMERIC(18,4)` in minor units per unit and quantities `NUMERIC(14,3)`; both are `Decimal` in Python. Exactly **one rounding point**: `line_amount = round_half_up(quantity × unit_price)` in `app/domain/money.py`; nothing else rounds. Rounding mode: ROUND_HALF_UP (to whole tiyin).
- **Consequences:** integer sums are exact, so `invoice.total == sum(lines)` is provable (hypothesis) and enforced by a deferred DB trigger. The UI divides by 100 for display.

## D004 — Ledger design
- **Decision:** `ledger_entries` is append-only (DB trigger rejects UPDATE/DELETE). Signed amounts: **positive = tenant owes more** (invoice), **negative = tenant paid / credit**. Balance = `SUM(amount)` per lease (never stored). Corrections are *reversing entries* (`reverses_id`). A negative balance is credit that automatically offsets the next invoice's due amount.
- `payment_allocations` and `invoice_lines` are also append-only; invoices are immutable except `status` (issued→void). Both enforced by triggers, tested.

## D005 — Tariff change mid-period
- **Decision:** the whole consumption between two confirmed readings is priced with the tariff effective on the **current (later) reading's date**. Tiers apply per billing interval to that consumption. See BILLING_RULES.md.
- **Why:** deterministic, explainable to a tenant, matches the spec ("tariff effective on reading date"). Splitting by days would need interpolated readings.

## D006 — Enums as VARCHAR + CHECK
Native PG enums are painful to migrate; VARCHAR + CHECK keeps Alembic simple and is still enforced by the DB.

## D007 — Test DB strategy
Tests run against a real PostgreSQL 16 database `rento_test`, created fresh each session and migrated with the real Alembic migrations; tables are TRUNCATEd between tests (TRUNCATE is not blocked by the append-only row triggers).

## D008 — Presigned POST (not PUT)
S3 presigned **POST** policies can enforce `content-length-range` and `Content-Type` on the storage side; presigned PUT cannot cap size. The server additionally `HEAD`s the object on submit.
