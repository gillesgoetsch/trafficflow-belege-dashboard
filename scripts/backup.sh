#!/usr/bin/env bash
# Daily backup. Runs inside the `backup` container (alpine + postgresql-client + aws-cli).
# - Dumps Postgres
# - Tars /data/receipts
# - Optionally uploads to S3-compatible storage
set -euo pipefail

if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
  echo "$(date -Iseconds) backup: skipped (BACKUP_S3_BUCKET not set)"
  exit 0
fi

STAMP=$(date +%Y%m%d-%H%M%S)
TMP=/tmp/belege-backup-${STAMP}
mkdir -p "$TMP"

echo "$(date -Iseconds) backup: pg_dump"
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "${POSTGRES_HOST:-db}" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --clean --if-exists --no-owner --format=custom \
    -f "$TMP/db.dump"

echo "$(date -Iseconds) backup: tarball receipts"
tar -cJf "$TMP/receipts.tar.xz" -C /data receipts

echo "$(date -Iseconds) backup: upload"
export AWS_ACCESS_KEY_ID="$BACKUP_S3_KEY"
export AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET"
AWS_ARGS=( --region "${BACKUP_S3_REGION:-auto}" )
[ -n "${BACKUP_S3_ENDPOINT:-}" ] && AWS_ARGS+=( --endpoint-url "$BACKUP_S3_ENDPOINT" )

aws s3 cp "$TMP/db.dump" "s3://$BACKUP_S3_BUCKET/db/belege-${STAMP}.dump" "${AWS_ARGS[@]}"
aws s3 cp "$TMP/receipts.tar.xz" "s3://$BACKUP_S3_BUCKET/files/receipts-${STAMP}.tar.xz" "${AWS_ARGS[@]}"

rm -rf "$TMP"
echo "$(date -Iseconds) backup: done"
