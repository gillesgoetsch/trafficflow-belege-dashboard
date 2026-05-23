"""All SQLAlchemy ORM models.

Keeping everything in one file is intentional — the schema is the system's
contract and reading it top-to-bottom should be possible. Indexes are declared
inline.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


# --- Enums --------------------------------------------------------------------


class ReceiptStatus(str, enum.Enum):
    processing = "processing"
    processed = "processed"
    review_needed = "review_needed"
    archived = "archived"
    failed = "failed"


class ClassificationLayer(str, enum.Enum):
    layer1 = "1"
    layer2 = "2"
    layer3 = "3"
    manual = "manual"


class ConnectorType(str, enum.Enum):
    local = "local"
    onedrive = "onedrive"
    bexio = "bexio"


class SyncStatus(str, enum.Enum):
    pending = "pending"
    synced = "synced"
    failed = "failed"
    skipped = "skipped"


class MatchType(str, enum.Enum):
    sender_domain = "sender_domain"
    sender_email = "sender_email"
    subject_contains = "subject_contains"
    body_contains = "body_contains"
    plus_alias = "plus_alias"
    sender_contains = "sender_contains"


class EmailMessageStatus(str, enum.Enum):
    pending = "pending"
    classified = "classified"
    rendered = "rendered"
    finished = "finished"
    review_needed = "review_needed"
    failed = "failed"
    not_a_receipt = "not_a_receipt"


class PaymentMethod(str, enum.Enum):
    credit_card = "credit_card"
    bank_transfer = "bank_transfer"
    twint = "twint"
    cash = "cash"
    paypal = "paypal"
    other = "other"
    unknown = "unknown"


# --- Users --------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="admin", server_default="admin", nullable=False)

    organizations: Mapped[list[Organization]] = relationship(
        secondary="user_organizations", lazy="selectin", viewonly=True,
    )


class UserOrganization(Base):
    __tablename__ = "user_organizations"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrganizationRoutingRule(Base, TimestampMixin):
    """Route an incoming receipt to the right org based on patterns in the
    body / sender / subject. Used when one mailbox receives bills for several
    legal entities (e.g. Meta Ads invoices for multiple AGs)."""
    __tablename__ = "organization_routing_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


# --- Organizations & sub-entities --------------------------------------------


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_email: Mapped[str] = mapped_column(String(255), nullable=False)
    default_currency: Mapped[str] = mapped_column(String(8), default="CHF", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Zurich", nullable=False)
    filename_template: Mapped[str] = mapped_column(
        String(255),
        default="{date}_{provider}_{client}_{amount}-{currency}",
        nullable=False,
    )

    mailboxes: Mapped[list[Mailbox]] = relationship(back_populates="organization", cascade="all,delete")
    clients: Mapped[list[Client]] = relationship(back_populates="organization", cascade="all,delete")
    receipts: Mapped[list[Receipt]] = relationship(back_populates="organization", cascade="all,delete")
    connectors: Mapped[list[Connector]] = relationship(back_populates="organization", cascade="all,delete")


class Mailbox(Base, TimestampMixin):
    __tablename__ = "mailboxes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    imap_user: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    folder: Mapped[str] = mapped_column(String(128), default="INBOX", nullable=False)
    batch_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_uid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="mailboxes")
    messages: Mapped[list[EmailMessage]] = relationship(back_populates="mailbox", cascade="all,delete")

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_org_mailbox_email"),
    )


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    default_currency: Mapped[str | None] = mapped_column(String(8))
    icon: Mapped[str | None] = mapped_column(String(64))

    rules: Mapped[list[ProviderRule]] = relationship(back_populates="provider", cascade="all,delete")


class ProviderRule(Base, TimestampMixin):
    __tablename__ = "provider_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType, name="match_type"), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    provider: Mapped[Provider] = relationship(back_populates="rules")


class Client(Base, TimestampMixin):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16))

    organization: Mapped[Organization] = relationship(back_populates="clients")
    mappings: Mapped[list[ClientMapping]] = relationship(back_populates="client", cascade="all,delete")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_org_client_slug"),
    )


class ClientMapping(Base, TimestampMixin):
    __tablename__ = "client_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id", ondelete="SET NULL"))

    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType, name="match_type"), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)

    client: Mapped[Client] = relationship(back_populates="mappings")


# --- Email + receipts ---------------------------------------------------------


class EmailMessage(Base, TimestampMixin):
    """Raw IMAP message tracking — primary idempotency key for the pipeline."""

    __tablename__ = "email_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    mailbox_id: Mapped[int] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    message_id: Mapped[str] = mapped_column(String(998), nullable=False)
    imap_uid: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str | None] = mapped_column(Text)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_email: Mapped[str | None] = mapped_column(String(255))
    to_address: Mapped[str | None] = mapped_column(String(998))
    raw_size: Mapped[int | None] = mapped_column(Integer)
    raw_path: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[EmailMessageStatus] = mapped_column(
        Enum(EmailMessageStatus, name="email_msg_status"),
        default=EmailMessageStatus.pending,
        nullable=False,
        index=True,
    )

    mailbox: Mapped[Mailbox] = relationship(back_populates="messages")
    receipts: Mapped[list[Receipt]] = relationship(back_populates="email_message")

    __table_args__ = (
        UniqueConstraint("mailbox_id", "message_id", name="uq_mailbox_message_id"),
        Index("ix_email_msg_received", "received_at"),
    )


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    mailbox_id: Mapped[int | None] = mapped_column(ForeignKey("mailboxes.id", ondelete="SET NULL"))
    email_message_id: Mapped[int | None] = mapped_column(ForeignKey("email_messages.id", ondelete="SET NULL"))
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id", ondelete="SET NULL"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))

    # Metadata
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(8))
    invoice_number: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str | None] = mapped_column(String(8))

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    # source: email | upload | api | scanner

    classification_layer: Mapped[ClassificationLayer] = mapped_column(
        Enum(ClassificationLayer, name="classification_layer"),
        default=ClassificationLayer.layer1,
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0, nullable=False)
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus, name="receipt_status"),
        default=ReceiptStatus.processing,
        nullable=False,
        index=True,
    )

    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method"),
        default=PaymentMethod.unknown,
        server_default="unknown",
        nullable=False,
        index=True,
    )
    brand: Mapped[str | None] = mapped_column(String(64), index=True)

    # Accountant fields
    notes: Mapped[str | None] = mapped_column(Text)
    vat_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    vat_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    bookkeeping_ref: Mapped[str | None] = mapped_column(String(128))

    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    processing_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    review_reason: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="receipts")
    email_message: Mapped[EmailMessage | None] = relationship(back_populates="receipts")
    provider: Mapped[Provider | None] = relationship()
    client: Mapped[Client | None] = relationship()
    sync_targets: Mapped[list[SyncTarget]] = relationship(back_populates="receipt", cascade="all,delete")

    __table_args__ = (
        Index("ix_receipts_org_status_date", "organization_id", "status", "document_date"),
        Index("ix_receipts_provider", "provider_id"),
    )


# --- Connectors + sync targets -----------------------------------------------


class Connector(Base, TimestampMixin):
    __tablename__ = "connectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    type: Mapped[ConnectorType] = mapped_column(Enum(ConnectorType, name="connector_type"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted JSON

    organization: Mapped[Organization] = relationship(back_populates="connectors")


class SyncTarget(Base, TimestampMixin):
    __tablename__ = "sync_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), index=True)

    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), default=SyncStatus.pending, nullable=False
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    receipt: Mapped[Receipt] = relationship(back_populates="sync_targets")
    connector: Mapped[Connector] = relationship()

    __table_args__ = (
        UniqueConstraint("receipt_id", "connector_id", name="uq_sync_target"),
    )


# --- Audit log (kept light; main audit lives in receipts.processing_log) -----


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
