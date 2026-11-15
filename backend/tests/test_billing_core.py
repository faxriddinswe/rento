"""Pure billing core: example tests + hypothesis property tests (no DB)."""

import itertools
from datetime import date, timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.billing.allocation import allocate_fifo
from app.billing.core import (
    AdjustmentIn,
    InvoiceRequest,
    LeaseIn,
    MeterIn,
    MissingTariff,
    ReadingIn,
    TariffIn,
    TierIn,
    build_invoice,
)
from app.billing.periods import (
    next_billing_date,
    period_for,
    period_starts_between,
)
from app.domain.money import line_amount, prorate, round_minor

RENT = 300_000_000


def lease(start=date(2026, 1, 1), end=None, rent=RENT, bd=1, due=10):
    return LeaseIn(start, end, rent, bd, due)


def rd(d, v, **kw):
    return ReadingIn(uuid4(), d, D(v), **kw)


def meter(readings, tariffs, kind="electricity", **kw):
    return MeterIn(uuid4(), kind, "M1", tuple(readings), tuple(tariffs), **kw)


T100 = TariffIn(date(2026, 1, 1), None, D("100000"))


# ---------------- money -----------------
def test_round_half_up():
    assert [round_minor(D(x)) for x in ("0.5", "1.5", "2.5", "2.4999", "0.4999")] == [1, 2, 3, 2, 0]
    assert line_amount(D("10.5"), D("100.5")) == 1055  # 1055.25 -> 1055
    assert line_amount(D("0.001"), D("500")) == 1  # 0.5 -> 1 (half up)


def test_prorate_examples():
    assert prorate(300_000, 15, 30) == 150_000
    assert prorate(100, 1, 3) == 33  # 33.33
    assert prorate(100, 2, 3) == 67  # 66.67
    with pytest.raises(ValueError):
        prorate(1, 1, 0)


# ---------------- periods -----------------
def test_next_billing_date():
    assert next_billing_date(date(2026, 1, 1), 1) == date(2026, 2, 1)
    assert next_billing_date(date(2026, 1, 3), 5) == date(2026, 1, 5)
    assert next_billing_date(date(2026, 12, 20), 5) == date(2027, 1, 5)


def test_period_full_and_partial():
    p = period_for(date(2026, 1, 1), None, 1, date(2026, 2, 1))
    assert (p.start, p.end, p.days, p.cycle_days, p.is_partial) == (
        date(2026, 2, 1),
        date(2026, 2, 28),
        28,
        28,
        False,
    )
    first = period_for(date(2026, 2, 15), None, 5, date(2026, 2, 15))
    assert (first.end, first.days, first.cycle_days) == (date(2026, 3, 4), 18, 28)
    last = period_for(date(2026, 1, 1), date(2026, 2, 20), 1, date(2026, 2, 1))
    assert (last.end, last.days, last.is_partial) == (date(2026, 2, 20), 20, True)
    assert period_for(date(2026, 1, 1), date(2026, 1, 31), 1, date(2026, 2, 1)) is None
    with pytest.raises(ValueError):
        period_for(date(2026, 1, 1), None, 1, date(2026, 2, 2))


# ---------------- rent -----------------
def test_first_invoice_full_rent_no_utilities():
    d = build_invoice(
        InvoiceRequest(
            lease(),
            date(2026, 1, 1),
            is_first=True,
            meters=(meter([rd(date(2026, 1, 1), 1000)], [T100]),),
        )
    )
    assert d is not None
    assert [(x.kind, x.amount) for x in d.lines] == [("rent", RENT)]
    assert d.total == RENT and d.due_date == date(2026, 1, 11)


def test_prorated_first_and_last_month():
    first = build_invoice(
        InvoiceRequest(lease(date(2026, 2, 15), bd=5), date(2026, 2, 15), is_first=True)
    )
    assert first.lines[0].amount == prorate(RENT, 18, 28)
    assert "18/28" in first.lines[0].description
    last = build_invoice(InvoiceRequest(lease(end=date(2026, 2, 20)), date(2026, 2, 1)))
    assert last.lines[0].amount == prorate(RENT, 20, 28)


def test_no_invoice_after_lease_end():
    assert build_invoice(InvoiceRequest(lease(end=date(2026, 1, 31)), date(2026, 2, 1))) is None


# ---------------- utilities -----------------
def test_utility_line_basic():
    r0, r1 = rd(date(2026, 1, 1), 1000), rd(date(2026, 2, 1), "1100.5")
    m = meter([r0, r1], [T100], last_billed_reading_id=r0.id)
    d = build_invoice(InvoiceRequest(lease(), date(2026, 2, 1), meters=(m,)))
    u = d.lines[1]
    assert u.kind == "utility" and u.quantity == D("100.5")
    assert u.amount == line_amount(D("100.5"), D("100000")) == 10_050_000
    assert (u.reading_from_id, u.reading_to_id) == (r0.id, r1.id)
    assert d.total == RENT + 10_050_000


def test_readings_after_invoice_date_are_ignored():
    r0, r1, late = (
        rd(date(2026, 1, 1), 1000),
        rd(date(2026, 2, 1), 1100),
        rd(date(2026, 2, 10), 1500),
    )
    d = build_invoice(
        InvoiceRequest(
            lease(),
            date(2026, 2, 1),
            meters=(meter([r0, r1, late], [T100], last_billed_reading_id=r0.id),),
        )
    )
    assert d.lines[1].quantity == D(100)


def test_tariff_change_uses_tariff_on_latest_reading_date():
    old = TariffIn(date(2026, 1, 1), date(2026, 1, 31), D("100000"))
    new = TariffIn(date(2026, 2, 1), None, D("150000"))
    r0, r1 = rd(date(2026, 1, 1), 0), rd(date(2026, 2, 1), 100)
    d = build_invoice(
        InvoiceRequest(
            lease(),
            date(2026, 2, 1),
            meters=(meter([r0, r1], [old, new], last_billed_reading_id=r0.id),),
        )
    )
    assert d.lines[1].unit_price == D("150000") and d.lines[1].amount == 15_000_000
    # reading dated 1/31 -> old tariff applies to the whole interval
    r1b = rd(date(2026, 1, 31), 100)
    d = build_invoice(
        InvoiceRequest(
            lease(),
            date(2026, 2, 1),
            meters=(meter([r0, r1b], [old, new], last_billed_reading_id=r0.id),),
        )
    )
    assert d.lines[1].unit_price == D("100000")


def test_tiered_tariff_one_line_per_segment():
    t = TariffIn(
        date(2026, 1, 1),
        None,
        D(0),
        (TierIn(D(100), D("100000")), TierIn(D(200), D("200000")), TierIn(None, D("400000"))),
    )
    r0, r1 = rd(date(2026, 1, 1), 0), rd(date(2026, 2, 1), 250)
    d = build_invoice(
        InvoiceRequest(
            lease(), date(2026, 2, 1), meters=(meter([r0, r1], [t], last_billed_reading_id=r0.id),)
        )
    )
    util = d.lines[1:]
    assert [(x.quantity, x.unit_price, x.amount) for x in util] == [
        (D(100), D("100000"), 10_000_000),
        (D(100), D("200000"), 20_000_000),
        (D(50), D("400000"), 20_000_000),
    ]
    # consumption inside first tier only -> single line
    r1 = rd(date(2026, 2, 1), 40)
    d = build_invoice(
        InvoiceRequest(
            lease(), date(2026, 2, 1), meters=(meter([r0, r1], [t], last_billed_reading_id=r0.id),)
        )
    )
    assert len(d.lines) == 2


def test_missing_reading_creates_pending_line_then_catch_up_adjustment():
    r0 = rd(date(2026, 1, 1), 1000)
    m = meter([r0], [T100], last_billed_reading_id=r0.id)
    feb = build_invoice(InvoiceRequest(lease(), date(2026, 2, 1), meters=(m,)))
    pend = feb.lines[1]
    assert pend.pending_reading and pend.amount == 0 and pend.kind == "utility"
    # reading arrives later; next invoice carries the catch-up as an adjustment line
    r1 = rd(date(2026, 2, 25), 1200)
    m2 = meter([r0, r1], [T100], last_billed_reading_id=r0.id, prior_pending=True)
    mar = build_invoice(InvoiceRequest(lease(), date(2026, 3, 1), meters=(m2,)))
    adj = mar.lines[1]
    assert adj.kind == "adjustment" and adj.amount == 20_000_000 and not adj.pending_reading


def test_no_readings_at_all_after_first_invoice_is_pending():
    d = build_invoice(InvoiceRequest(lease(), date(2026, 2, 1), meters=(meter([], [T100]),)))
    assert d.lines[1].pending_reading


def test_missing_tariff_raises():
    r0, r1 = rd(date(2026, 1, 1), 0), rd(date(2026, 2, 1), 5)
    with pytest.raises(MissingTariff):
        build_invoice(
            InvoiceRequest(
                lease(),
                date(2026, 2, 1),
                meters=(meter([r0, r1], [], last_billed_reading_id=r0.id),),
            )
        )


def test_meter_replacement_baseline():
    r0 = rd(date(2026, 1, 1), 1000)
    swap = rd(date(2026, 1, 25), 5, is_baseline=True, replaced_final_value=D(1080))
    r2 = rd(date(2026, 2, 1), 30)
    d = build_invoice(
        InvoiceRequest(
            lease(),
            date(2026, 2, 1),
            meters=(meter([r0, swap, r2], [T100], last_billed_reading_id=r0.id),),
        )
    )
    assert d.lines[1].quantity == D(80 + 25)
    # unknown old final value: consumption on old meter is not billed, only the new meter's
    swap2 = rd(date(2026, 1, 25), 5, is_baseline=True)
    d = build_invoice(
        InvoiceRequest(
            lease(),
            date(2026, 2, 1),
            meters=(meter([r0, swap2, r2], [T100], last_billed_reading_id=r0.id),),
        )
    )
    assert d.lines[1].quantity == D(25)


def test_adjustments_and_final_invoice():
    adj = AdjustmentIn(uuid4(), -5_000_000, "Discount")
    d = build_invoice(InvoiceRequest(lease(), date(2026, 2, 1), adjustments=(adj,)))
    assert d.lines[-1].amount == -5_000_000 and d.total == RENT - 5_000_000
    r0, r1 = rd(date(2026, 1, 1), 0), rd(date(2026, 2, 10), 50)
    ended = lease(end=date(2026, 2, 10))
    final = build_invoice(
        InvoiceRequest(
            ended,
            date(2026, 2, 11),
            is_final=True,
            meters=(meter([r0, r1], [T100], last_billed_reading_id=r0.id),),
        )
    )
    assert [x.kind for x in final.lines] == ["utility"] and final.lines[0].amount == 5_000_000
    assert final.issue_date == date(2026, 2, 11)
    with pytest.raises(ValueError):
        build_invoice(InvoiceRequest(ended, date(2026, 2, 12), is_final=True))


def test_deterministic():
    r0, r1 = rd(date(2026, 1, 1), 1), rd(date(2026, 2, 1), 9)
    req = InvoiceRequest(
        lease(), date(2026, 2, 1), meters=(meter([r0, r1], [T100], last_billed_reading_id=r0.id),)
    )
    assert build_invoice(req) == build_invoice(req)


# ---------------- hypothesis -----------------
dec_qty = st.decimals(min_value=0, max_value=100_000, places=3)
dec_price = st.decimals(min_value=0, max_value=10_000_000, places=4)


@given(dec_qty, dec_price)
def test_line_amount_is_int_within_half_unit(qty, price):
    a = line_amount(qty, price)
    assert isinstance(a, int)
    assert abs(D(a) - qty * price) <= D("0.5")


@given(st.integers(0, 10**12), st.integers(1, 366))
def test_prorate_bounds_and_identity(amount, cycle):
    assert prorate(amount, cycle, cycle) == amount
    assert prorate(amount, 0, cycle) == 0
    for days in {1, cycle // 2, cycle}:
        assert 0 <= prorate(amount, days, cycle) <= amount


@given(st.integers(0, 10**9), st.integers(2, 60), st.integers(1, 59))
def test_prorate_splits_never_lose_more_than_one_unit(amount, cycle, k):
    k = min(k, cycle - 1)
    assert abs(prorate(amount, k, cycle) + prorate(amount, cycle - k, cycle) - amount) <= 1


@st.composite
def scenario(draw):
    start = draw(st.dates(min_value=date(2025, 1, 1), max_value=date(2027, 12, 31)))
    bd = draw(st.integers(1, 28))
    end = draw(st.one_of(st.none(), st.dates(min_value=start, max_value=date(2029, 1, 1))))
    rent = draw(st.integers(0, 10**10))
    n_meters = draw(st.integers(0, 3))
    meters = []
    for _ in range(n_meters):
        n = draw(st.integers(0, 5))
        d, v = start, D(draw(st.integers(0, 10_000)))
        rs = []
        for _ in range(n):
            d = d + timedelta(days=draw(st.integers(1, 40)))
            v = v + draw(st.decimals(min_value=0, max_value=900, places=3))
            rs.append(rd(d, v))
        tiers = draw(
            st.one_of(
                st.none(), st.just((TierIn(D(50), D("1234.5678")), TierIn(None, D("99999.9999"))))
            )
        )
        t = TariffIn(date(2020, 1, 1), None, draw(dec_price), tiers)
        meters.append(
            meter(
                rs,
                [t],
                last_billed_reading_id=rs[0].id if rs and draw(st.booleans()) else None,
                prior_pending=draw(st.booleans()),
            )
        )
    adjs = tuple(
        AdjustmentIn(uuid4(), draw(st.integers(-(10**7), 10**7)), "adj")
        for _ in range(draw(st.integers(0, 3)))
    )
    return LeaseIn(start, end, rent, bd, 10), tuple(meters), adjs


@settings(max_examples=300, deadline=None)
@given(scenario(), st.integers(0, 24), st.booleans())
def test_invoice_total_equals_sum_of_lines_and_amounts_are_exact(sc, k, first):
    ls, meters, adjs = sc
    starts = period_starts_between(
        ls.start_date, ls.end_date, ls.billing_day, ls.start_date, date(2030, 1, 1)
    )
    ps = starts[min(k, len(starts) - 1)]
    d = build_invoice(InvoiceRequest(ls, ps, meters=meters, adjustments=adjs, is_first=first))
    if d is None:
        return
    assert d.total == sum(x.amount for x in d.lines)
    for x in d.lines:
        assert isinstance(x.amount, int)
        if x.kind == "utility" and not x.pending_reading and x.reading_from_id:
            assert x.amount == line_amount(x.quantity, x.unit_price)
        if x.pending_reading:
            assert x.amount == 0
        if x.kind == "rent":
            assert 0 <= x.amount <= ls.monthly_rent


@settings(max_examples=200, deadline=None)
@given(
    st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31)),
    st.integers(1, 28),
    st.one_of(st.none(), st.integers(0, 900)),
)
def test_periods_tile_the_lease_without_gaps_or_overlap(start, bd, end_offset):
    end = None if end_offset is None else start + timedelta(days=end_offset)
    horizon = date(2028, 1, 1)
    starts = period_starts_between(start, end, bd, start, horizon)
    assert starts[0] == start
    periods = [period_for(start, end, bd, s) for s in starts]
    for a, b in itertools.pairwise(periods):
        assert a is not None and b is not None
        assert a.end + timedelta(days=1) == b.start
    last = periods[-1]
    assert last is not None
    if end is not None:
        assert last.end == end or last.end < end  # never beyond lease end
        assert last.end <= end


@settings(max_examples=300, deadline=None)
@given(st.lists(st.integers(0, 10**6), max_size=8), st.lists(st.integers(0, 10**6), max_size=8))
def test_fifo_allocation_properties(pay_amounts, inv_amounts):
    pays = [(uuid4(), a) for a in pay_amounts]
    invs = [(uuid4(), a) for a in inv_amounts]
    allocs = allocate_fifo(pays, invs)
    assert all(a.amount > 0 for a in allocs)
    for pid, rem in pays:
        assert sum(a.amount for a in allocs if a.payment_id == pid) <= rem
    for iid, owed in invs:
        assert sum(a.amount for a in allocs if a.invoice_id == iid) <= owed
    assert sum(a.amount for a in allocs) == min(sum(pay_amounts), sum(inv_amounts))
    # oldest-first: an invoice gets money only if every earlier invoice is fully covered
    got = {iid: sum(a.amount for a in allocs if a.invoice_id == iid) for iid, _ in invs}
    for idx, (iid, _owed) in enumerate(invs):
        if got[iid] > 0:
            assert all(got[j] == o for j, o in invs[:idx])
