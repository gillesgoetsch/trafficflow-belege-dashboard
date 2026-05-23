// Shared API types — mirror the FastAPI Pydantic schemas.

export type Layer = "1" | "2" | "3" | "manual";
export type ReceiptStatus = "processing" | "processed" | "review_needed" | "archived" | "failed";
export type ConnectorType = "local" | "onedrive" | "bexio";
export type MatchType =
  | "sender_domain"
  | "sender_email"
  | "subject_contains"
  | "body_contains"
  | "plus_alias"
  | "sender_contains";

export type SyncStatus = "pending" | "synced" | "failed" | "skipped";

export type PaymentMethod =
  | "credit_card"
  | "bank_transfer"
  | "twint"
  | "cash"
  | "paypal"
  | "other"
  | "unknown";

export const PAYMENT_METHOD_LABEL: Record<PaymentMethod, string> = {
  credit_card: "Kreditkarte",
  bank_transfer: "Banküberweisung",
  twint: "Twint",
  cash: "Bargeld",
  paypal: "PayPal",
  other: "Sonstige",
  unknown: "Unbekannt",
};

export type DocumentType = "receipt" | "document" | "upcoming" | "other";
export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  receipt: "Rechnung/Beleg",
  document: "Dokument",
  upcoming: "Vorabrechnung",
  other: "Sonstige",
};

export interface User {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  totp_enabled: boolean;
}

export interface Organization {
  id: number;
  name: string;
  primary_email: string;
  default_currency: string;
  timezone: string;
  filename_template: string;
}

export interface Mailbox {
  id: number;
  organization_id: number;
  email: string;
  imap_host: string;
  imap_port: number;
  imap_user: string;
  use_tls: boolean;
  folder: string;
  batch_interval_minutes: number;
  enabled: boolean;
  last_sync_at: string | null;
  last_uid: number;
  last_error: string | null;
}

export interface Provider {
  id: number;
  slug: string;
  display_name: string;
  category: string | null;
  default_currency: string | null;
  icon: string | null;
}

export interface ProviderRule {
  id: number;
  provider_id: number;
  organization_id: number | null;
  match_type: MatchType;
  match_value: string;
  priority: number;
}

export interface Client {
  id: number;
  organization_id: number;
  name: string;
  slug: string;
  color: string | null;
}

export interface ClientMapping {
  id: number;
  client_id: number;
  provider_id: number | null;
  match_type: MatchType;
  match_value: string;
}

export interface SyncTarget {
  id: number;
  connector_id: number;
  status: SyncStatus;
  synced_at: string | null;
  external_id: string | null;
  error: string | null;
}

export interface Receipt {
  id: number;
  organization_id: number;
  mailbox_id: number | null;
  provider_id: number | null;
  client_id: number | null;
  document_date: string | null;   // date of issue (Rechnungsdatum)
  due_date: string | null;        // payment due (Fälligkeitsdatum)
  received_at: string | null;
  amount: string | null;
  currency: string | null;
  invoice_number: string | null;
  language: string | null;
  filename: string;
  source: string;
  classification_layer: Layer;
  confidence: string;
  status: ReceiptStatus;
  payment_method: PaymentMethod;
  brand: string | null;
  document_type: DocumentType;
  notes: string | null;
  vat_rate: string | null;
  vat_amount: string | null;
  booked_at: string | null;
  bookkeeping_ref: string | null;
  review_reason: string | null;
  created_at: string;
}

export interface ReceiptDetail extends Receipt {
  raw_metadata: Record<string, any>;
  processing_log: Array<Record<string, any>>;
  sync_targets: SyncTarget[];
}

export interface ReceiptList {
  items: Receipt[];
  total: number;
  page: number;
  page_size: number;
}

export interface Connector {
  id: number;
  organization_id: number;
  type: ConnectorType;
  name: string;
  enabled: boolean;
}

export interface ConnectorDetail extends Connector {
  config: Record<string, any>;
}

export interface ReviewItem {
  receipt_id: number;
  organization_id: number;
  subject: string | null;
  sender: string | null;
  received_at: string | null;
  suggested_provider_id: number | null;
  suggested_provider_slug: string | null;
  confidence: number;
  reason: string | null;
  amount: string | null;
  currency: string | null;
  payment_method: string | null;
  brand: string | null;
}

export interface DashboardKPIs {
  receipts_total: number;
  receipts_this_month: number;
  receipts_last_month: number;
  total_amount_this_month: string;
  review_queue_size: number;
  sync_failed_count: number;
  layer_distribution: Record<string, number>;
}

export interface DashboardCharts {
  by_day: { bucket: string; value: number }[];
  top_providers: { provider_id: number | null; provider: string; count: number; total_amount: string }[];
  by_payment_method: { payment_method: string; count: number; total_amount: string }[];
}
