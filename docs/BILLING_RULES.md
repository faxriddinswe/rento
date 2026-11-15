# Billing rules (plain language)

All amounts are integer **minor units (tiyin)**; the UI divides by 100. All dates are local dates in
**Asia/Tashkent**. Tariff prices in this repo's seed data are **FAKE**; real tariffs are entered by the owner.

## 1. When invoices are made
* A lease is split into **periods**. The first period starts on the lease start date; every later
  period starts on the lease's **billing day** (1–28). A period ends the day before the next billing
  day (or on the lease end date).
* The **ARQ job runs daily at 00:10 Asia/Tashkent** (and once at worker start). For every lease it
  creates the invoice of each period that *started within the last 7 days* and has no invoice yet.
  The 7-day window makes a few days of worker downtime harmless.
* **Idempotent:** `UNIQUE(lease_id, period_start)` plus a row lock on the lease. Running the job twice
  (or concurrently) never creates a second invoice. Older gaps (e.g. a lease entered in the past)
  are back-filled with `POST /leases/{id}/billing/run` — periods are billed oldest first.
* The **issue date is the period start**, due date = issue date + `due_days`.

## 2. Rent
* Rent is billed **in advance** for the period that starts on the invoice date.
* **Pro-rating** (first and last partial periods): `rent × days_in_period / days_in_full_cycle`,
  where the full cycle is the billing-day-to-billing-day month the period belongs to; rounded once, half up.
  Example: lease starts 15 Feb, billing day 5 → cycle 5 Feb–4 Mar = 28 days; period 15 Feb–4 Mar = 18 days → rent × 18/28.
  A lease that ends 20 Feb (billing day 1) pays rent × 20/28 for February.

## 3. Utilities (meters)
* Billed **in arrears** on the next invoice: consumption between the **last billed confirmed reading**
  and the **latest confirmed reading dated on/before the invoice date**.
* The **first invoice of a lease has no utility lines** (nothing has been consumed yet).
* **Tariff change rule (D005):** the whole consumption between the two readings is priced with the
  tariff effective on the **later reading's date**. No splitting by days.
* **Tiered tariffs:** consumption is split across tiers (marginal); each tier segment is its own line.
* **No tariff** for the reading date → no invoice for that lease, the owner gets a `billing_failed`
  notification; the next run (or manual run) bills it once the tariff exists.
* **Missing reading** → a zero-amount line marked *pending reading*, owner and tenant are notified.
  The invoice is never edited later. When a reading finally arrives, the next invoice contains an
  **adjustment line** ("catch-up") covering everything since the last billed reading.
* **Lower reading than the previous confirmed one** is rejected for tenants (`reading_lower_than_previous`).
  The owner records a **new baseline** ("meter replaced") with the old meter's last value:
  consumption up to that value is still billed, then counting restarts from the new meter's value.
* A reading higher than a *later* confirmed reading is also rejected (readings must be monotonic in time).

## 4. Adjustments, final invoice, voiding
* Manual charges/discounts (`POST /leases/{id}/adjustments`) wait and are added as lines to the **next** invoice.
* After a lease ends, a **final invoice** (period = end date + 1) is created if there is something to bill
  (last utilities / pending adjustments). It has no rent.
* Issued invoices are immutable (DB trigger). A mistake is corrected by **voiding** (reversing ledger
  entry) and/or an adjustment on the next invoice.

## 5. Money, ledger, payments
* **Ledger** is append-only: invoice = `+total`, payment = `−amount`; balance = sum of entries
  (`>0` tenant owes, `<0` tenant has credit). Corrections are *reversing entries*.
* **Payments** are allocated **FIFO**: oldest unpaid invoice first, partially if needed.
* **Overpayment** stays as unallocated credit and is applied automatically to the next invoice when it is issued.
* **Rounding:** `ROUND_HALF_UP` to whole tiyin, exactly once per line (`domain/money.py`). The invoice total is
  the integer sum of its lines (also enforced by a deferred DB trigger).
