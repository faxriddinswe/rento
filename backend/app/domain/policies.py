"""Authorization policy: one pure function, ``can(actor, action, resource)``.

No role checks are scattered through the API; every endpoint resolves a ``Resource`` and asks here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class Action(StrEnum):
    PROPERTY_CREATE = "property.create"
    PROPERTY_READ = "property.read"
    PROPERTY_UPDATE = "property.update"
    UNIT_MANAGE = "unit.manage"
    LEASE_READ = "lease.read"
    LEASE_MANAGE = "lease.manage"
    METER_READ = "meter.read"
    METER_MANAGE = "meter.manage"
    TARIFF_READ = "tariff.read"
    TARIFF_MANAGE = "tariff.manage"
    READING_SUBMIT = "reading.submit"
    READING_READ = "reading.read"
    READING_REVIEW = "reading.review"
    INVOICE_READ = "invoice.read"
    BILLING_RUN = "billing.run"
    PAYMENT_READ = "payment.read"
    PAYMENT_RECORD = "payment.record"
    PAYMENT_REVERSE = "payment.reverse"
    LEDGER_READ = "ledger.read"
    DOCUMENT_READ = "document.read"
    DOCUMENT_GENERATE = "document.generate"
    TEMPLATE_MANAGE = "template.manage"
    AUDIT_READ = "audit.read"
    MANAGER_MANAGE = "manager.manage"
    DASHBOARD_READ = "dashboard.read"


# Permissions an owner may delegate to a manager of one property.
MANAGER_GRANTABLE: frozenset[Action] = frozenset(
    {
        Action.PROPERTY_READ,
        Action.UNIT_MANAGE,
        Action.LEASE_READ,
        Action.LEASE_MANAGE,
        Action.METER_READ,
        Action.METER_MANAGE,
        Action.TARIFF_READ,
        Action.TARIFF_MANAGE,
        Action.READING_READ,
        Action.READING_REVIEW,
        Action.INVOICE_READ,
        Action.PAYMENT_READ,
        Action.PAYMENT_RECORD,
        Action.LEDGER_READ,
        Action.DOCUMENT_READ,
        Action.DOCUMENT_GENERATE,
        Action.DASHBOARD_READ,
    }
)

# What a tenant may do on resources of *their own* lease.
TENANT_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.LEASE_READ,
        Action.METER_READ,
        Action.READING_SUBMIT,
        Action.READING_READ,
        Action.INVOICE_READ,
        Action.PAYMENT_READ,
        Action.LEDGER_READ,
        Action.DOCUMENT_READ,
    }
)


@dataclass(frozen=True)
class Actor:
    id: UUID
    role: str  # owner | manager | tenant
    # manager only: property_id -> granted permission strings
    managed: Mapping[UUID, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Resource:
    """Ownership facts about the thing being accessed."""

    owner_id: UUID | None = None  # owner of the property it belongs to
    property_id: UUID | None = None
    tenant_id: UUID | None = None  # tenant of the lease it belongs to (if any)


def can(actor: Actor, action: Action, resource: Resource | None = None) -> bool:
    res = resource or Resource()
    if actor.role == "owner":
        if action is Action.PROPERTY_CREATE:
            return True
        return res.owner_id is not None and res.owner_id == actor.id
    if actor.role == "manager":
        if action not in MANAGER_GRANTABLE or res.property_id is None:
            return False
        return action.value in actor.managed.get(res.property_id, frozenset())
    if actor.role == "tenant":
        return action in TENANT_ACTIONS and res.tenant_id is not None and res.tenant_id == actor.id
    return False
