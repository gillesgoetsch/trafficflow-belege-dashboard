#!/usr/bin/env bash
# One-shot VPS bootstrap script.
# Assumes Debian 12 / Ubuntu 22.04+. Installs docker, clones repo, sets up .env scaffold.
set -euo pipefail

REPO_URL="${1:-https://github.com/your-user/trafficflow-belege-dashboard.git}"
TARGET="${2:-/srv/belege}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (use sudo)."
  exit 1
fi

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg git ufw

# Docker CE
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg || true
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | tee /etc/apt/sources.list.d/docker.list >/dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

# Firewall
ufw default deny incoming || true
ufw default allow outgoing || true
ufw allow OpenSSH || true
ufw allow http
ufw allow https
yes | ufw enable

# Repo
mkdir -p "$TARGET"
chown -R "$SUDO_USER:$SUDO_USER" "$TARGET" || true
if [ ! -d "$TARGET/.git" ]; then
  sudo -u "${SUDO_USER:-root}" git clone "$REPO_URL" "$TARGET"
fi

cd "$TARGET"
if [ ! -f .env ]; then
  cp .env.example .env
  # generate secrets
  python3 - <<'PY' >> .env.gen
import secrets
print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
from cryptography.fernet import Fernet
print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
print(f"DEPLOY_WEBHOOK_SECRET={secrets.token_urlsafe(32)}")
PY
  echo
  echo "------------------------------------------------------"
  echo "Generated secrets:"
  cat .env.gen
  echo
  echo "Now edit $TARGET/.env to set:"
  echo "  - DOMAIN, ACME_EMAIL"
  echo "  - POSTGRES_PASSWORD, ADMIN_PASSWORD"
  echo "  - ANTHROPIC_API_KEY"
  echo "  - paste the generated secrets above into the matching keys"
  echo "------------------------------------------------------"
fi

echo "Done. Next:"
echo "  cd $TARGET"
echo "  vi .env"
echo "  docker compose up -d --build"
