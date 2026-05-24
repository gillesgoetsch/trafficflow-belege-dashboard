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


class ConnectorMode(str, enum.Enum):
    off = "off"
    dry_run = "dry_run"
    live = "live"


class SyncStatus(str, enum.Enum):
    pending = "pending"
    synced = "synced"
    failed = "failed"
    skipped = "skipped"
    dry_run_ok = "dry_run_ok"


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


class DocumentType(str, enum.Enum):
    receipt = "receipt"     # paid or payable invoice — accounting flow
    document = "document"   # legit non-invoice (packing slip, attestation, contract)
    upcoming = "upcoming"   # invoice issued for a future billing date (Notion etc)
    other = "other"         # uncategorizable


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
    # document_date == date of issue (Rechnungsdatum) — the canonical date for table views.
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
        Enum(
            ClassificationLayer,
            name="classification_layer",
            values_callable=lambda x: [e.value for e in x],
        ),
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

    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type"),
        default=DocumentType.receipt,
        server_default="receipt",
        nullable=False,
        index=True,
    )

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
    # mode supersedes `enabled` for richer control. `enabled` is kept for backwards-compat
    # with the connector list UI; sync logic checks mode first (off → skip, dry_run → log only).
    mode: Mapped[ConnectorMode] = mapped_column(
        Enum(ConnectorMode, name="connector_mode"),
        default=ConnectorMode.live,
        server_default="live",
        nullable=False,
    )
    # When mode==live and auto_book is True, Bexio bills are immediately booked
    # instead of left as drafts. Default False — safer.
    auto_book: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
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
    # Snapshot of connector.mode at the time this attempt ran — needed because
    # the connector mode can change later and we want the audit trail to stay true.
    mode: Mapped[ConnectorMode | None] = mapped_column(
        Enum(ConnectorMode, name="connector_mode", create_type=False)
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    response_status_code: Mapped[int | None] = mapped_column(Integer)

    receipt: Mapped[Receipt] = relationship(back_populates="sync_targets")
    connector: Mapped[Connector] = relationship()

    __table_args__ = (
        UniqueConstraint("receipt_id", "connector_id", name="uq_sync_target"),
    )


class ProviderAccountMapping(Base, TimestampMixin):
    """Bookkeeping mapping per (organization × provider).

    `account_code` is the Bexio chart-of-accounts entry to charge (e.g. "6510").
    `vat_code` optionally overrides VAT code lookup (e.g. "VST077"). Used by the
    Bexio connector to build kb_bill positions with correct accounting fields.
    """
    __tablename__ = "provider_account_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    account_code: Mapped[str] = mapped_column(String(32), nullable=False)
    vat_code: Mapped[str | None] = mapped_column(String(32))

    provider: Mapped[Provider] = relationship()
    organization: Mapped[Organization] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "organization_id", name="uq_provider_account_mapping"
        ),
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


# --- Email skip rules + brand routes ----------------------------------------


class EmailSkipRule(Base, TimestampMixin):
    """Patterns that mark an inbound email as not-a-receipt before classification.

    Catches privacy-policy / terms-of-service / newsletter emails from senders
    that *also* send real receipts (Spotify, Meta, etc.) — those would otherwise
    pass Layer 1 and get turned into a 0 CHF receipt.
    """
    __tablename__ = "email_skip_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True,
    )  # null = applies to every org
    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType, name="match_type"), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class BrandRoute(Base, TimestampMixin):
    """Re-route a receipt to a different organization based on body/subject content.

    Example: a Meta Ads receipt lands on the TrafficFlow inbox, but the body
    contains "Transaction for FIMS" — FIMS is a brand of kingnature, so the
    receipt belongs in the kingnature org with brand="fims".
    """
    __tablename__ = "brand_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    target_organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
    )
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL"), nullable=True,
    )  # optional — only fire when matching this specific provider
    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType, name="match_type"), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


# --- Inbound cloud folders ---------------------------------------------------


class InboundFolderType(str, enum.Enum):
    nextcloud_share = "nextcloud_share"
    onedrive_share = "onedrive_share"
    gdrive_share = "gdrive_share"
    local_mount = "local_mount"


class InboundFileStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    processed = "processed"
    failed = "failed"
    not_a_receipt = "not_a_receipt"


class InboundFolder(Base, TimestampMixin):
    """A cloud folder (shared link) we poll for new files to ingest."""
    __tablename__ = "inbound_folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    type: Mapped[InboundFolderType] = mapped_column(
        Enum(InboundFolderType, name="inbound_folder_type", create_type=False,
             values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    share_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    config_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted JSON
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    batch_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))


class InboundFile(Base, TimestampMixin):
    """Per-file state for files seen in an inbound folder."""
    __tablename__ = "inbound_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int] = mapped_column(
        ForeignKey("inbound_folders.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    remote_id: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    size: Mapped[int | None] = mapped_column(BigInteger)
    remote_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[InboundFileStatus] = mapped_column(
        Enum(InboundFileStatus, name="inbound_file_status", create_type=False,
             values_callable=lambda x: [e.value for e in x]),
        default=InboundFileStatus.pending, nullable=False,
    )
    receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        UniqueConstraint("folder_id", "remote_id", name="uq_inbound_file_folder_remote"),
    )
