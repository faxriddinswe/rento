"""Pure billing core: no DB, no clock, no I/O. Same input -> same invoice (see BILLING_RULES.md).

Rules implemented here:
* Rent is billed in advance for the period starting on the invoice date; first/last partial
  periods are pro-rated by days (single rounding, domain.money.prorate).
* Utilities are billed in arrears: consumption between the last *billed* confirmed reading and the
  latest confirmed reading dated on/before the invoice date, priced with the tariff effective on
  that latest reading's date (D005). Tiers produce one line per tier segment.
* No new reading -> a zero 'pending reading' line; the consumption is caught up (as an
  'adjustment' line) on the next invoice that has a reading. Issued invoices are never edited.
* A baseline reading (meter replaced) restarts the meter: consumption up to the old meter's final
  value is still billed, the new baseline value is the new starting point.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.billing.periods import period_for
from app.domain.money import line_amount, prorate

LABELS: dict[str, str] = {
    "rent": "Ijara haqi",
    "rent_prorated": "Ijara haqi (qisman davr)",
    "pending": "ko'rsatkich kutilmoqda",
    "catch_up": "Hisob-kitob (oldingi davr ko'rsatkichi kechikkan)",
    "days": "kun",
    "tier": "tarif bosqichi",
}
KIND_LABELS: dict[str, str] = {
    "electricity": "Elektr energiya",
    "water_cold": "Sovuq suv",
    "water_hot": "Issiq suv",
    "gas": "Gaz",
    "heating": "Isitish",
    "other": "Boshqa xizmat",
}


@dataclass(frozen=True)
class TierIn:
    up_to: Decimal | None
    price: Decimal


@dataclass(frozen=True)
class TariffIn:
    effective_from: date
    effective_to: date | None
    unit_price: Decimal
    tiers: tuple[TierIn, ...] | None = None

    def covers(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)


@dataclass(frozen=True)
class ReadingIn:
    """A *confirmed* reading."""

    id: UUID
    reading_date: date
    value: Decimal
    is_baseline: bool = False
    replaced_final_value: Decimal | None = None


@dataclass(frozen=True)
class MeterIn:
    id: UUID
    kind: str
    label: str
    readings: tuple[ReadingIn, ...]  # confirmed readings, any order
    tariffs: tuple[TariffIn, ...]
    last_billed_reading_id: UUID | None = None
    prior_pending: bool = False  # the previous invoice had a pending line for this meter


@dataclass(frozen=True)
class AdjustmentIn:
    id: UUID
    amount: int
    description: str


@dataclass(frozen=True)
class LeaseIn:
    start_date: date
    end_date: date | None
    monthly_rent: int
    billing_day: int
    due_days: int


@dataclass(frozen=True)
class InvoiceRequest:
    lease: LeaseIn
    period_start: date
    meters: tuple[MeterIn, ...] = ()
    adjustments: tuple[AdjustmentIn, ...] = ()
    is_first: bool = False  # no earlier invoice for this lease -> no utility lines
    is_final: bool = False  # final settlement invoice after the lease ended (no rent)


@dataclass(frozen=True)
class LineDraft:
    kind: str  # rent | utility | adjustment
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: int
    meter_id: UUID | None = None
    reading_from_id: UUID | None = None
    reading_to_id: UUID | None = None
    pending_reading: bool = False
    adjustment_id: UUID | None = None


@dataclass(frozen=True)
class InvoiceDraft:
    period_start: date
    period_end: date
    issue_date: date
    due_date: date
    lines: tuple[LineDraft, ...]

    @property
    def total(self) -> int:
        return sum(line.amount for line in self.lines)


class MissingTariff(Exception):
    def __init__(self, meter_id: UUID, kind: str, on: date) -> None:
        super().__init__(f"No {kind} tariff effective on {on}")
        self.meter_id, self.kind, self.on = meter_id, kind, on


def _sorted(readings: Sequence[ReadingIn]) -> list[ReadingIn]:
    return sorted(readings, key=lambda r: (r.reading_date, str(r.id)))


def consumption_between(
    sorted_readings: Sequence[ReadingIn], start: ReadingIn, end: ReadingIn
) -> Decimal:
    """Consumption from reading ``start`` (exclusive) up to ``end`` (inclusive)."""
    total = Decimal(0)
    prev = start
    started = False
    for r in sorted_readings:
        if r is start or r.id == start.id:
            started = True
            continue
        if not started:
            continue
        if r.is_baseline:
            # meter replaced: old meter's final value closes the old segment (if known)
            if r.replaced_final_value is not None and r.replaced_final_value > prev.value:
                total += r.replaced_final_value - prev.value
        else:
            total += max(r.value - prev.value, Decimal(0))
        prev = r
        if r.id == end.id:
            break
    return total


def _price_lines(
    meter: MeterIn, tariff: TariffIn, qty: Decimal, frm: ReadingIn, to: ReadingIn, catch_up: bool
) -> list[LineDraft]:
    kind = "adjustment" if catch_up else "utility"
    base = f"{KIND_LABELS.get(meter.kind, meter.kind)} ({meter.label})".replace(" ()", "")
    base += f" {frm.reading_date:%d.%m.%Y}-{to.reading_date:%d.%m.%Y}"
    if catch_up:
        base = f"{LABELS['catch_up']}: {base}"
    if qty == 0:
        return [LineDraft(kind, f"{base}: 0", Decimal(0), Decimal(0), 0, meter.id, frm.id, to.id)]
    if not tariff.tiers:
        return [
            LineDraft(
                kind,
                base,
                qty,
                tariff.unit_price,
                line_amount(qty, tariff.unit_price),
                meter.id,
                frm.id,
                to.id,
            )
        ]
    lines: list[LineDraft] = []
    lower = Decimal(0)
    for tier in tariff.tiers:
        upper = tier.up_to if tier.up_to is not None else qty
        seg = min(qty, upper) - lower
        if seg > 0:
            desc = f"{base} [{LABELS['tier']}: {lower}-{tier.up_to if tier.up_to is not None else '∞'}]"
            lines.append(
                LineDraft(
                    kind,
                    desc,
                    seg,
                    tier.price,
                    line_amount(seg, tier.price),
                    meter.id,
                    frm.id,
                    to.id,
                )
            )
        lower = upper
        if lower >= qty:
            break
    return lines


def _utility_lines(meter: MeterIn, cutoff: date) -> list[LineDraft]:
    readings = _sorted([r for r in meter.readings if r.reading_date <= cutoff])
    label = f"{KIND_LABELS.get(meter.kind, meter.kind)} ({meter.label})".replace(" ()", "")
    pending = LineDraft(
        "utility",
        f"{label}: {LABELS['pending']}",
        Decimal(0),
        Decimal(0),
        0,
        meter.id,
        None,
        None,
        pending_reading=True,
    )
    by_id = {r.id: r for r in readings}
    start = by_id.get(meter.last_billed_reading_id) if meter.last_billed_reading_id else None
    if start is None:
        start = readings[0] if readings else None
    latest = readings[-1] if readings else None
    if start is None or latest is None or latest.id == start.id:
        return [pending]
    tariff = next((t for t in meter.tariffs if t.covers(latest.reading_date)), None)
    if tariff is None:
        raise MissingTariff(meter.id, meter.kind, latest.reading_date)
    qty = consumption_between(readings, start, latest)
    return _price_lines(meter, tariff, qty, start, latest, catch_up=meter.prior_pending)


def build_invoice(req: InvoiceRequest) -> InvoiceDraft | None:
    """Compute the invoice for the period starting at ``req.period_start`` (None = nothing to bill)."""
    lease = req.lease
    lines: list[LineDraft] = []
    if req.is_final:
        if lease.end_date is None:
            raise ValueError("final invoice requires an ended lease")
        p_start = p_end = lease.end_date + timedelta(days=1)
        issue = p_start
        if req.period_start != p_start:
            raise ValueError("final invoice period_start must be end_date + 1 day")
    else:
        period = period_for(lease.start_date, lease.end_date, lease.billing_day, req.period_start)
        if period is None:
            return None
        p_start, p_end, issue = period.start, period.end, period.start
        if period.is_partial:
            amount = prorate(lease.monthly_rent, period.days, period.cycle_days)
            unit = (Decimal(lease.monthly_rent) / Decimal(period.cycle_days)).quantize(
                Decimal("0.0001")
            )
            desc = (
                f"{LABELS['rent_prorated']} {p_start:%d.%m.%Y}-{p_end:%d.%m.%Y} "
                f"({period.days}/{period.cycle_days} {LABELS['days']})"
            )
            lines.append(LineDraft("rent", desc, Decimal(period.days), unit, amount))
        else:
            desc = f"{LABELS['rent']} {p_start:%d.%m.%Y}-{p_end:%d.%m.%Y}"
            lines.append(
                LineDraft("rent", desc, Decimal(1), Decimal(lease.monthly_rent), lease.monthly_rent)
            )
    if not req.is_first:
        for meter in sorted(req.meters, key=lambda m: (m.kind, m.label, str(m.id))):
            lines.extend(_utility_lines(meter, issue))
    for adj in req.adjustments:
        lines.append(
            LineDraft(
                "adjustment",
                adj.description,
                Decimal(1),
                Decimal(adj.amount),
                adj.amount,
                adjustment_id=adj.id,
            )
        )
    if not lines:
        return None
    return InvoiceDraft(p_start, p_end, issue, issue + timedelta(days=lease.due_days), tuple(lines))
