"""Pydantic v2 schemas for request/response shapes.

Single file: short enough to be readable, and avoids circular imports.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import (
    ClassificationLayer,
    ConnectorType,
    EmailMessageStatus,
    MatchType,
    PaymentMethod,
    ReceiptStatus,
    SyncStatus,
)


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth ---


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    otp: str | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserOut(_ORM):
    id: int
    email: EmailStr
    is_active: bool
    is_admin: bool
    totp_enabled: bool = False


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class TotpEnrollOut(BaseModel):
    secret: str
    uri: str
    qr_data_url: str


class TotpConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


# --- Organizations ---


class OrganizationIn(BaseModel):
    name: str
    primary_email: EmailStr
    default_currency: str = "CHF"
    timezone: str = "Europe/Zurich"
    filename_template: str | None = None


class OrganizationOut(_ORM):
    id: int
    name: str
    primary_email: EmailStr
    default_currency: str
    timezone: str
    filename_template: str


# --- Mailboxes ---


class MailboxIn(BaseModel):
    organization_id: int
    email: EmailStr
    imap_host: str
    imap_port: int = 993
    imap_user: str
    imap_password: str
    use_tls: bool = True
    folder: str = "INBOX"
    batch_interval_minutes: int = 30
    enabled: bool = True


class MailboxPatch(BaseModel):
    email: EmailStr | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_user: str | None = None
    imap_password: str | None = None
    use_tls: bool | None = None
    folder: str | None = None
    batch_interval_minutes: int | None = None
    enabled: bool | None = None


class MailboxOut(_ORM):
    id: int
    organization_id: int
    email: str
    imap_host: str
    imap_port: int
    imap_user: str
    use_tls: bool
    folder: str
    batch_interval_minutes: int
    enabled: bool
    last_sync_at: datetime | None
    last_uid: int
    last_error: str | None


# --- Providers ---


class ProviderIn(BaseModel):
    slug: str
    display_name: str
    category: str | None = None
    default_currency: str | None = None
    icon: str | None = None


class ProviderOut(_ORM):
    id: int
    slug: str
    display_name: str
    category: str | None
    default_currency: str | None
    icon: str | None


class ProviderRuleIn(BaseModel):
    provider_id: int
    organization_id: int | None = None
    match_type: MatchType
    match_value: str
    priority: int = 100


class ProviderRuleOut(_ORM):
    id: int
    provider_id: int
    organization_id: int | None
    match_type: MatchType
    match_value: str
    priority: int


# --- Clients ---


class ClientIn(BaseModel):
    organization_id: int
    name: str
    slug: str
    color: str | None = None


class ClientOut(_ORM):
    id: int
    organization_id: int
    name: str
    slug: str
    color: str | None


class ClientMappingIn(BaseModel):
    client_id: int
    provider_id: int | None = None
    match_type: MatchType
    match_value: str


class ClientMappingOut(_ORM):
    id: int
    client_id: int
    provider_id: int | None
    match_type: MatchType
    match_value: str


# --- Receipts ---


class ReceiptOut(_ORM):
    id: int
    organization_id: int
    mailbox_id: int | None
    provider_id: int | None
    client_id: int | None
    document_date: datetime | None         # date of issue (Rechnungsdatum)
    due_date: datetime | None = None        # payment due (Fälligkeitsdatum)
    received_at: datetime | None
    amount: Decimal | None
    currency: str | None
    invoice_number: str | None
    language: str | None
    filename: str
    source: str
    classification_layer: ClassificationLayer
    confidence: Decimal
    status: ReceiptStatus
    payment_method: PaymentMethod
    brand: str | None
    notes: str | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    booked_at: datetime | None = None
    bookkeeping_ref: str | None = None
    review_reason: str | None
    created_at: datetime


class ReceiptDetail(ReceiptOut):
    raw_metadata: dict[str, Any]
    processing_log: list[dict[str, Any]]
    sync_targets: list[SyncTargetOut] = []


class ReceiptPatch(BaseModel):
    provider_id: int | None = None
    client_id: int | None = None
    document_date: datetime | None = None
    due_date: datetime | None = None
    amount: Decimal | None = None
    currency: str | None = None
    invoice_number: str | None = None
    status: ReceiptStatus | None = None
    payment_method: PaymentMethod | None = None
    brand: str | None = None
    notes: str | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    booked_at: datetime | None = None
    bookkeeping_ref: str | None = None


class ReceiptListOut(BaseModel):
    items: list[ReceiptOut]
    total: int
    page: int
    page_size: int


# --- Sync targets / Connectors ---


class SyncTargetOut(_ORM):
    id: int
    connector_id: int
    status: SyncStatus
    synced_at: datetime | None
    external_id: str | None
    error: str | None


class ConnectorIn(BaseModel):
    organization_id: int
    type: ConnectorType
    name: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorOut(_ORM):
    id: int
    organization_id: int
    type: ConnectorType
    name: str
    enabled: bool


class ConnectorDetail(ConnectorOut):
    config: dict[str, Any]


# --- Review queue ---


class ReviewItemOut(BaseModel):
    receipt_id: int
    subject: str | None
    sender: str | None
    received_at: datetime | None
    suggested_provider_id: int | None
    suggested_provider_slug: str | None
    confidence: float
    reason: str | None
    amount: Decimal | None = None
    currency: str | None = None
    payment_method: str | None = None
    brand: str | None = None


class ReviewDecision(BaseModel):
    action: str  # accept | reject | reassign
    provider_id: int | None = None
    client_id: int | None = None
    create_rule: bool = False


# --- Dashboard ---


class DashboardKPIs(BaseModel):
    receipts_total: int
    receipts_this_month: int
    receipts_last_month: int
    total_amount_this_month: Decimal
    review_queue_size: int
    sync_failed_count: int
    layer_distribution: dict[str, int]


class TimeSeriesPoint(BaseModel):
    bucket: str
    value: float


class ProviderShare(BaseModel):
    provider_id: int | None
    provider: str
    count: int
    total_amount: Decimal


class PaymentMethodShare(BaseModel):
    payment_method: str
    count: int
    total_amount: Decimal


class DashboardCharts(BaseModel):
    by_day: list[TimeSeriesPoint]
    top_providers: list[ProviderShare]
    by_payment_method: list[PaymentMethodShare] = Field(default_factory=list)


# Recursive references
LoginOut.model_rebuild()
ReceiptDetail.model_rebuild()
