"""All persistent entities. Money columns are BIGINT *minor units* (tiyin); see D003."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    JSONB,
    UUID,
    ExcludeConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, uuid_pk

ROLES = ("owner", "manager", "tenant")
METER_KINDS = ("electricity", "water_cold", "water_hot", "gas", "heating", "other")
READING_STATUSES = ("pending", "confirmed", "rejected")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="role"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    locale: Mapped[str] = mapped_column(String(5), default="uz", server_default="uz")
    created_at: Mapped[datetime] = created_at_col()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class Property(Base):
    __tablename__ = "properties"
    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = created_at_col()
    units: Mapped[list["Unit"]] = relationship(back_populates="property")


class PropertyManager(Base):
    """Manager access to a property with explicit permission strings (see domain/policies.py)."""

    __tablename__ = "property_managers"
    property_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("property_id", "name", name="uq_units_property_name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    created_at: Mapped[datetime] = created_at_col()
    property: Mapped[Property] = relationship(back_populates="units")


class Lease(Base):
    __tablename__ = "leases"
    __table_args__ = (
        CheckConstraint("status IN ('active','ended','cancelled')", name="status"),
        CheckConstraint("billing_day BETWEEN 1 AND 28", name="billing_day"),
        CheckConstraint("monthly_rent >= 0", name="rent_nonneg"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates"),
        # No two non-cancelled leases of one unit may overlap in time.
        ExcludeConstraint(
            ("unit_id", "="),
            (text("daterange(start_date, coalesce(end_date, 'infinity'::date), '[]')"), "&&"),
            using="gist",
            where=text("status <> 'cancelled'"),
            name="ex_leases_no_overlap",
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    monthly_rent: Mapped[int] = mapped_column(BigInteger)
    deposit: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    billing_day: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    due_days: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_at: Mapped[datetime] = created_at_col()
    unit: Mapped[Unit] = relationship()


class Invite(Base):
    """One-time tenant invite; the signed token's jti is stored so it can be used once."""

    __tablename__ = "invites"
    id: Mapped[uuid.UUID] = uuid_pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class Meter(Base):
    __tablename__ = "meters"
    __table_args__ = (CheckConstraint(_in("kind", METER_KINDS), name="kind"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    serial: Mapped[str] = mapped_column(String(100), default="", server_default="")
    unit_label: Mapped[str] = mapped_column(String(16), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_col()


class Tariff(Base):
    """Price history per property+kind. Prices in minor units per 1 unit of consumption.

    `tiers`: optional JSON list [{"up_to": "100", "price": "40000"}, ..., {"up_to": null, ...}];
    when present it replaces `unit_price` (marginal/progressive tiers per billing period).
    """

    __tablename__ = "tariffs"
    __table_args__ = (
        CheckConstraint(_in("kind", METER_KINDS), name="kind"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates"),
        ExcludeConstraint(
            ("property_id", "="),
            ("kind", "="),
            (
                text("daterange(effective_from, coalesce(effective_to, 'infinity'::date), '[]')"),
                "&&",
            ),
            using="gist",
            name="ex_tariffs_no_overlap",
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tiers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class MeterReading(Base):
    __tablename__ = "meter_readings"
    __table_args__ = (
        CheckConstraint(_in("status", READING_STATUSES), name="status"),
        CheckConstraint("value >= 0", name="value_nonneg"),
        Index("ix_meter_readings_meter_date", "meter_id", "reading_date"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    meter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meters.id"), index=True)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leases.id"), index=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reading_date: Mapped[date] = mapped_column(Date)
    photo_key: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    # Meter replaced: this value is a new baseline. `replaced_final_value` = last value of the old meter.
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    replaced_final_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at_col()


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("lease_id", "period_start", name="uq_invoices_lease_period"),
        CheckConstraint("status IN ('issued','void')", name="status"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    total: Mapped[int] = mapped_column(BigInteger)
    previous_balance: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="issued", server_default="issued")
    created_at: Mapped[datetime] = created_at_col()
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", order_by="InvoiceLine.sort"
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (CheckConstraint("kind IN ('rent','utility','adjustment')", name="kind"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    sort: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal(0))
    amount: Mapped[int] = mapped_column(BigInteger)
    meter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meters.id"))
    reading_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meter_readings.id"))
    reading_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meter_readings.id"))
    pending_reading: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class LeaseAdjustment(Base):
    """Manual charge/discount waiting to be included in the lease's next invoice."""

    __tablename__ = "lease_adjustments"
    __table_args__ = (CheckConstraint("amount <> 0", name="amount_nonzero"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    created_at: Mapped[datetime] = created_at_col()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_pos"),
        CheckConstraint("method IN ('cash','card','transfer','other')", name="method"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(16), default="cash")
    reference: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(500))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class PaymentAllocation(Base):
    """Append-only. invoice_id NULL is never stored — unallocated remainder = credit (derived).
    Reversing a payment appends negative rows."""

    __tablename__ = "payment_allocations"
    __table_args__ = (CheckConstraint("amount <> 0", name="amount_nonzero"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_col()


class LedgerEntry(Base):
    """Append-only (DB trigger blocks UPDATE/DELETE). amount>0 = tenant owes more; <0 = tenant paid/credited."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('invoice','payment','payment_reversal','invoice_void','adjustment')",
            name="entry_type",
        ),
        CheckConstraint("amount <> 0", name="amount_nonzero"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(24))
    amount: Mapped[int] = mapped_column(BigInteger)
    ref_type: Mapped[str] = mapped_column(String(24))
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()


class ContractTemplate(Base):
    __tablename__ = "contract_templates"
    __table_args__ = (
        UniqueConstraint("owner_id", "version", name="uq_contract_templates_owner_version"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("kind IN ('contract','invoice')", name="kind"),
        UniqueConstraint("kind", "ref_id", "version", name="uq_documents_kind_ref_version"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(16))
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending','sent','failed','skipped')", name="status"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # whose data the action concerns; owners may only read audit rows with their own owner_id
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
