"""Pure FIFO allocation of payment credit to open invoices (oldest invoice first)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Alloc:
    payment_id: UUID
    invoice_id: UUID
    amount: int


def allocate_fifo(
    payments: Sequence[tuple[UUID, int]], invoices: Sequence[tuple[UUID, int]]
) -> list[Alloc]:
    """``payments``: (id, unallocated remainder) oldest first; ``invoices``: (id, still owed)
    oldest first. Returns allocations; never over-allocates either side."""
    out: list[Alloc] = []
    inv_ids: list[UUID] = [inv_id for inv_id, owed in invoices if owed > 0]
    owed_left: list[int] = [owed for _, owed in invoices if owed > 0]
    i = 0
    for pay_id, rem in payments:
        while rem > 0 and i < len(inv_ids):
            take = min(rem, owed_left[i])
            out.append(Alloc(pay_id, inv_ids[i], take))
            rem -= take
            owed_left[i] -= take
            if owed_left[i] == 0:
                i += 1
    return out
