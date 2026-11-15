"""Billing-period arithmetic (pure). Dates only, no timezone logic (callers pass local dates)."""

from dataclasses import dataclass
from datetime import date, timedelta


def _add_month(d: date, day: int) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, day)


def next_billing_date(d: date, billing_day: int) -> date:
    """First billing date strictly after ``d`` (billing_day is 1..28 so it exists every month)."""
    if d.day < billing_day:
        return d.replace(day=billing_day)
    return _add_month(d, billing_day)


def billing_date_on_or_before(d: date, billing_day: int) -> date:
    if d.day >= billing_day:
        return d.replace(day=billing_day)
    prev_year, prev_month = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    return date(prev_year, prev_month, billing_day)


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive
    cycle_days: int  # length of the full billing cycle this period belongs to

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def is_partial(self) -> bool:
        return self.days != self.cycle_days


def is_period_start(lease_start: date, billing_day: int, d: date) -> bool:
    """A period starts on the lease start date and on every later billing day."""
    return d == lease_start or (d > lease_start and d.day == billing_day)


def period_for(
    lease_start: date, lease_end: date | None, billing_day: int, period_start: date
) -> Period | None:
    """The period beginning at ``period_start`` or None if the lease is not active then."""
    if not is_period_start(lease_start, billing_day, period_start):
        raise ValueError(f"{period_start} is not a period start for this lease")
    if lease_end is not None and lease_end < period_start:
        return None
    nxt = next_billing_date(period_start, billing_day)
    cycle_start = billing_date_on_or_before(period_start, billing_day)
    end = nxt - timedelta(days=1)
    if lease_end is not None and lease_end < end:
        end = lease_end
    return Period(start=period_start, end=end, cycle_days=(nxt - cycle_start).days)


def period_starts_between(
    lease_start: date, lease_end: date | None, billing_day: int, first: date, last: date
) -> list[date]:
    """All period starts of the lease within [first, last]."""
    out: list[date] = []
    d = lease_start
    while d <= last:
        if d >= first and (lease_end is None or d <= lease_end):
            out.append(d)
        d = next_billing_date(d, billing_day)
    return out
