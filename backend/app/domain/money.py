"""Money primitives. Amounts are int minor units (tiyin). THE one rounding rule lives here.

Rounding rule (D003): ROUND_HALF_UP to a whole minor unit, applied exactly once per invoice line.
"""

from decimal import ROUND_HALF_UP, Decimal


def round_minor(value: Decimal) -> int:
    """Round a Decimal amount in minor units to an int, half up. The only rounding in the system."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def line_amount(quantity: Decimal, unit_price: Decimal) -> int:
    """amount = round_half_up(quantity x unit_price)."""
    return round_minor(quantity * unit_price)


def prorate(amount: int, days: int, cycle_days: int) -> int:
    """Pro-rated share of ``amount`` for ``days`` of a ``cycle_days`` cycle (single rounding)."""
    if cycle_days <= 0 or days < 0:
        raise ValueError("cycle_days must be > 0 and days >= 0")
    return round_minor(Decimal(amount) * Decimal(days) / Decimal(cycle_days))
