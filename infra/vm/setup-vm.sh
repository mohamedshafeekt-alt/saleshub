#!/bin/bash
# =====================================================
# Sales CRM — one-time VM setup (root, idempotent). Additive only: the VM
# also runs innovault, whose containers, nginx site, folders and DB are
# not touched. Run from this directory:
#
#   bash setup-vm.sh "<sales-crm deploy public key line>"
#
# Creates /opt/sales-crm/{api,web,media}, installs rollback.sh, adds the
# sales-crm deploy key to the existing `deploy` user, enables a NEW nginx
# site on :8080 (validated with nginx -t, graceful reload) and opens
# 8080/tcp in UFW, and lets the API container (Docker network sales-crm-net,
# 172.31.0.0/16) reach Postgres for sales_crm_prod only. The database itself
# is created separately.
# =====================================================
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PUBKEY="${1:?usage: setup-vm.sh \"ssh-ed25519 AAAA... comment\"}"
[[ "$PUBKEY" =~ ^ssh-(ed25519|rsa)\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || { echo "not a public key line"; exit 1; }

echo "=== deploy user + sales-crm key"
id deploy >/dev/null 2>&1 || { echo "deploy user missing — run innovault's setup first"; exit 1; }
AUTH=/home/deploy/.ssh/authorized_keys
grep -qxF "$PUBKEY" "$AUTH" || echo "$PUBKEY" >> "$AUTH"
chown deploy:deploy "$AUTH"; chmod 600 "$AUTH"

echo "=== /opt/sales-crm"
install -d -m 750 -o deploy -g deploy /opt/sales-crm /opt/sales-crm/api /opt/sales-crm/web
# uploads: written by the API container's appuser (uid 10001)
install -d -m 750 -o 10001 -g 10001 /opt/sales-crm/media
install -m 755 -o root -g root "$HERE/rollback.sh" /opt/sales-crm/rollback.sh

echo "=== nginx site :8080 (new file; innovault site untouched)"
install -m 644 "$HERE/sales-crm-proxy.conf" /etc/nginx/snippets/sales-crm-proxy.conf
install -m 644 "$HERE/nginx-sales-crm.conf" /etc/nginx/sites-available/sales-crm
ln -sfn /etc/nginx/sites-available/sales-crm /etc/nginx/sites-enabled/sales-crm
if ! nginx -t; then
  rm -f /etc/nginx/sites-enabled/sales-crm
  echo "nginx -t failed — sales-crm site NOT enabled, nginx NOT reloaded"; exit 1
fi
systemctl reload nginx

echo "=== API Docker network + DB access (sales-crm only; innovault untouched)"
docker network inspect sales-crm-net >/dev/null 2>&1 || docker network create --subnet 172.31.0.0/16 sales-crm-net >/dev/null
HBA=/etc/postgresql/17/main/pg_hba.conf
LINE='host    sales_crm_prod    sales_crm_prod_user    172.31.0.0/16    scram-sha-256'
grep -qF "$LINE" "$HBA" || printf '\n# sales-crm-api container (Docker network sales-crm-net) — sales_crm DB/user only\n%s\n' "$LINE" >> "$HBA"
sudo -u postgres psql -XAt -c "select pg_reload_conf()" >/dev/null     # reload, not restart
ufw allow from 172.31.0.0/16 to any port 5432 proto tcp comment 'sales-crm-net containers -> postgres' >/dev/null

echo "=== UFW 8080"
ufw allow 8080/tcp comment 'sales-crm' >/dev/null
ufw status | grep 8080

echo "Done."
