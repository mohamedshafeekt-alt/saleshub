#!/bin/bash

# =====================================================
# Sales CRM API — build on the Bitbucket runner, ship the image to the VM
# over SSH (no registry), back up the running release, swap the container,
# health-check, and roll back automatically on failure.
#
# The pipeline NEVER touches the database: no dump, no migrations, no seed.
# The VM also runs innovault — everything here is scoped to sales-crm-*.
#
# Exported by bitbucket-pipelines.yml:  IMAGE_NAME, CONTAINER_NAME
# Bitbucket repository variables:
#   SSH_HOST, SSH_USER, SSH_PRIVATE_KEY_BASE64, SSH_KNOWN_HOSTS, HEALTH_URL,
#   CONFIG (JSON in the same format as our other projects: a "database"
#   block {username, password, database, ip_address, port} plus the app's
#   own keys). deploy.sh converts it to the APP_CONFIG the app reads
#   (db_name / db_username / db_password / db_host / db_port).
#
# VM layout — exactly ONE backup is kept (the last release that worked):
#   /opt/sales-crm/api/current/  api.env, release.json             ← running now
#   /opt/sales-crm/api/backup/   image.tar.gz, api.env, release.json ← rollback point
#   /opt/sales-crm/media/        uploaded files (mounted, survives deploys)
# Manual restore of backup/:  /opt/sales-crm/rollback.sh api
# =====================================================

for v in IMAGE_NAME CONTAINER_NAME SSH_HOST SSH_USER SSH_PRIVATE_KEY_BASE64 SSH_KNOWN_HOSTS HEALTH_URL CONFIG; do
  [ -n "${!v:-}" ] || { echo "ERROR: $v is not set — add it as a Bitbucket repository variable"; exit 1; }
done

# =====================================================
# Stop Script on Error
# =====================================================
set -euo pipefail

# =====================================================
# Build Variables
# =====================================================
export IMAGE_TAG=$BITBUCKET_BUILD_NUMBER
NEW_IMAGE="$IMAGE_NAME:$IMAGE_TAG"

# Health-check retry budget (used by both the primary and rollback health
# checks — defined early since rollback() can be called before the new
# container is up).
MAX_RETRIES=20
WARMUP_SECONDS=15

# VM layout
APP_DIR=/opt/sales-crm/api
CURRENT_DIR=$APP_DIR/current            # release that is running
BACKUP_DIR=$APP_DIR/backup              # the one rollback point
STAGING_DIR=$APP_DIR/backup.new         # backup being built during this deploy
ENV_NEW=$APP_DIR/api.env.new            # env for this deploy until it's healthy
MEDIA_DIR=/opt/sales-crm/media          # uploads (storage_backend=local)
APP_PORT=8200                           # published on 127.0.0.1 only — nginx :8080 is the way in
API_NET=sales-crm-net                   # 172.31.0.0/16 — pg_hba allows sales_crm_prod only from it
MEMORY_LIMIT=768m

export DOCKER_BUILDKIT=1

# =====================================================
# Debug Variables
# =====================================================
echo "========================================="
echo "IMAGE_NAME=$IMAGE_NAME"
echo "IMAGE_TAG=$IMAGE_TAG"
echo "CONTAINER_NAME=$CONTAINER_NAME"
echo "SSH_HOST=$SSH_HOST"
echo "HEALTH_URL=$HEALTH_URL"
echo "========================================="

# =====================================================
# Cleanup — always runs on exit (success or failure)
# Ensures the SSH key/known_hosts files are never left on the runner disk.
# =====================================================
SSH_KEY_FILE=""
KNOWN_HOSTS_FILE=""
trap 'rm -f "$SSH_KEY_FILE" "$KNOWN_HOSTS_FILE" .env && echo "Cleaned up credentials."' EXIT

# =====================================================
# SSH Deploy Configuration
# SSH_PRIVATE_KEY_BASE64 is the private key, base64-encoded, to survive
# Bitbucket's variable storage without newline/whitespace mangling.
# =====================================================
SSH_KEY_FILE=$(mktemp)
KNOWN_HOSTS_FILE=$(mktemp)
printf '%s' "$SSH_PRIVATE_KEY_BASE64" | base64 -d > "$SSH_KEY_FILE"
chmod 600 "$SSH_KEY_FILE"
echo "$SSH_KNOWN_HOSTS" > "$KNOWN_HOSTS_FILE"

SSH_OPTS="-i $SSH_KEY_FILE -o UserKnownHostsFile=$KNOWN_HOSTS_FILE -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes -o ServerAliveInterval=30"

remote() {
  # $1 = remote command string
  ssh $SSH_OPTS "$SSH_USER@$SSH_HOST" "$1"
}

remote "echo 'SSH OK — connected as' \$(whoami)@\$(hostname)"

# =====================================================
# Build Docker Image
# =====================================================
echo "========================================="
echo "Building Docker Image"
echo "========================================="

docker build -t "$NEW_IMAGE" .

# =====================================================
# Build Runtime .env from CONFIG
# CONFIG uses our standard format (a "database" block like innovault /
# neovault). It is validated, converted to the flat APP_CONFIG the app reads
# (app/core/config.py: db_name, db_username, db_password, db_host, db_port)
# and minified to one line — with the new image's own Python, so a malformed
# config fails here before anything on the VM is touched.
# Only key NAMES are printed; values are secrets.
# =====================================================
echo "========================================="
echo "Building .env from CONFIG (keys only)"
echo "========================================="

docker run --rm -e CONFIG -e EXPECTED_DB_HOST="$SSH_HOST" "$NEW_IMAGE" python -c '
import json, os, sys
try:
    c = json.loads(os.environ["CONFIG"])
except json.JSONDecodeError as e:
    sys.exit(f"ERROR: CONFIG is not valid JSON ({e.msg} at line {e.lineno} col {e.colno})")
db = c.get("database")
if not isinstance(db, dict):
    sys.exit("ERROR: CONFIG needs a \"database\" block: {username, password, database, ip_address, port}")
missing = [f"database.{k}" for k in ("username", "password", "database", "ip_address") if not db.get(k)]
missing += [k for k in ("secret_key", "smtp_host", "smtp_username", "smtp_password", "smtp_from_address") if k not in c]
if missing:
    sys.exit(f"ERROR: CONFIG is missing required keys: {missing}")
expected = os.environ["EXPECTED_DB_HOST"]
host = db["ip_address"]
if host != expected:
    sys.exit(f"ERROR: CONFIG.database.ip_address must be the server IP {expected} (the API container reaches Postgres there) — got {host!r}")
app = {k: v for k, v in c.items() if k != "database"}
app.update(db_name=db["database"], db_username=db["username"], db_password=db["password"],
           db_host=db["ip_address"], db_port=int(db.get("port", 5432)))
print("CONFIG keys:", ", ".join(c), "→ APP_CONFIG keys:", ", ".join(app), file=sys.stderr)
print("APP_CONFIG=" + json.dumps(app, separators=(",", ":")))
print("FORWARDED_ALLOW_IPS=*")
' > .env

# =====================================================
# Ship Image to VM (no registry — stream over SSH)
# =====================================================
echo "========================================="
echo "Shipping $NEW_IMAGE to $SSH_HOST"
echo "========================================="

docker save "$NEW_IMAGE" | gzip | ssh $SSH_OPTS "$SSH_USER@$SSH_HOST" 'gunzip | docker load'

# =====================================================
# Upload env for this deploy
# Written to api.env.new; it only becomes current/api.env once the new
# container is healthy.
# =====================================================
echo "========================================="
echo "Uploading env file"
echo "========================================="

remote "mkdir -p $CURRENT_DIR && rm -rf $STAGING_DIR"
ssh $SSH_OPTS "$SSH_USER@$SSH_HOST" "umask 077; cat > $ENV_NEW" < .env

# =====================================================
# Capture Currently Running Image (for rollback)
# =====================================================
echo "========================================="
echo "Capturing currently running image"
echo "========================================="

OLD_IMAGE=$(remote "docker inspect --format='{{.Config.Image}}' $CONTAINER_NAME" 2>/dev/null) || OLD_IMAGE=""

if [ -n "$OLD_IMAGE" ]; then
  echo "Currently running image: $OLD_IMAGE"
else
  echo "WARNING: no running container named $CONTAINER_NAME on $SSH_HOST — first deploy, automatic rollback unavailable this run"
fi

# Abort helper for failures BEFORE the running container is touched.
abort_untouched() {
  echo "ERROR: $1 — aborting. Running app untouched, existing backup untouched."
  remote "rm -rf $STAGING_DIR $ENV_NEW"
  exit 1
}

# =====================================================
# Stage Backup of the Running Release (backup.new/)
# image.tar.gz + api.env + release.json of what is running now. It only
# replaces backup/ if this deploy succeeds — so there is always exactly
# one backup: the last good release.
# =====================================================
echo "========================================="
echo "Staging backup of the running release"
echo "========================================="

if [ -n "$OLD_IMAGE" ]; then
  remote "mkdir -p $STAGING_DIR && chmod 700 $STAGING_DIR"
  echo "Saving image $OLD_IMAGE → backup.new/image.tar.gz"
  remote "docker save '$OLD_IMAGE' | nice -n 19 gzip > $STAGING_DIR/image.tar.gz" || abort_untouched "could not save the running image"
  remote "cp -p $CURRENT_DIR/api.env $STAGING_DIR/api.env" || abort_untouched "running release has no $CURRENT_DIR/api.env"
  remote "if [ -f $CURRENT_DIR/release.json ]; then cp $CURRENT_DIR/release.json $STAGING_DIR/release.json; \
          else printf '{\"image\": \"%s\"}\n' '$OLD_IMAGE' > $STAGING_DIR/release.json; fi"
  remote "chmod 600 $STAGING_DIR/* && ls -lh $STAGING_DIR"
else
  echo "Nothing running yet — no backup to stage."
fi

# =====================================================
# Health Check Helper
# =====================================================
wait_healthy() {
  local label="$1"
  set +e
  for i in $(seq 1 $MAX_RETRIES); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null || true)
    echo "$label health attempt $i/$MAX_RETRIES — HTTP $STATUS — $HEALTH_URL"
    if [ "$STATUS" = "200" ]; then
      set -e
      return 0
    fi
    sleep 15
  done
  set -e
  return 1
}

run_container() {
  # $1 = image, $2 = env file
  # Docker network sales-crm-net, port published on 127.0.0.1 only (shown
  # in docker ps; nginx :8080 is the sole way in). The API reaches Postgres
  # at the server IP (CONFIG database.ip_address).
  remote "docker run -d --name $CONTAINER_NAME \
    --network $API_NET \
    -p 127.0.0.1:$APP_PORT:8000 \
    --env-file $2 \
    -v $MEDIA_DIR:/app/media \
    --memory=$MEMORY_LIMIT \
    --log-opt max-size=10m --log-opt max-file=3 \
    --restart unless-stopped \
    '$1' uvicorn app.main:app --host 0.0.0.0 --port 8000"
}

# =====================================================
# Rollback Helper (automatic)
# Restores the release that was running (OLD_IMAGE + current/api.env),
# discards the staged backup (backup/ is untouched), then re-verifies
# health before failing the pipeline.
# =====================================================
rollback() {
  local reason="$1"
  echo "========================================="
  echo "ROLLBACK INITIATED: $reason"
  echo "========================================="

  echo "Last 50 log lines of the failed container:"
  remote "docker logs --tail 50 $CONTAINER_NAME" || true

  remote "rm -rf $STAGING_DIR $ENV_NEW"

  if [ -z "$OLD_IMAGE" ]; then
    echo "ERROR: No previous image was captured before this deploy — automatic rollback is not possible."
    echo "Manual intervention required. Current broken IMAGE_TAG: $IMAGE_TAG"
    exit 1
  fi

  echo "Rolling back to $OLD_IMAGE..."
  remote "docker stop $CONTAINER_NAME || true"
  remote "docker rm $CONTAINER_NAME || true"
  run_container "$OLD_IMAGE" "$CURRENT_DIR/api.env"

  echo "========================================="
  if wait_healthy "Rollback"; then
    echo "Rollback verified healthy — $OLD_IMAGE is running again."
  else
    echo "ERROR: Rollback deployed but did not become healthy within the retry window. Manual intervention required."
  fi
  echo "Deployment of IMAGE_TAG=$IMAGE_TAG FAILED. Reverted to $OLD_IMAGE."
  echo "========================================="
  exit 1
}

# =====================================================
# Deploy New Image
# =====================================================
echo "========================================="
echo "Deploying $NEW_IMAGE to $CONTAINER_NAME on $SSH_HOST"
echo "========================================="

remote "docker stop $CONTAINER_NAME || true"
remote "docker rm $CONTAINER_NAME || true"
run_container "$NEW_IMAGE" "$ENV_NEW" || rollback "Failed to start new container from $NEW_IMAGE"
echo "Container started from $NEW_IMAGE."

# =====================================================
# Warmup — wait for container to start
# =====================================================
echo "========================================="
echo "Waiting ${WARMUP_SECONDS}s for container startup"
echo "========================================="

sleep $WARMUP_SECONDS

# =====================================================
# Health Check Loop (every 15s, up to 5 min)
# =====================================================
echo "========================================="
echo "Starting health checks"
echo "========================================="

wait_healthy "Deploy" || rollback "Health check timed out after 5 min"

# =====================================================
# Promote: new release → current/, staged backup → backup/
# The previous backup is deleted — only one backup is ever kept.
# =====================================================
echo "========================================="
echo "Promoting release $IMAGE_TAG and rotating backup"
echo "========================================="

NEW_IMAGE_ID=$(remote "docker image inspect --format '{{.Id}}' '$NEW_IMAGE'")
DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

remote "mv $ENV_NEW $CURRENT_DIR/api.env \
  && printf '%s\n' '{' \
       '  \"build\": \"$IMAGE_TAG\",' \
       '  \"image\": \"$NEW_IMAGE\",' \
       '  \"image_id\": \"$NEW_IMAGE_ID\",' \
       '  \"commit\": \"${BITBUCKET_COMMIT:-unknown}\",' \
       '  \"branch\": \"${BITBUCKET_BRANCH:-unknown}\",' \
       '  \"deployed_at\": \"$DEPLOYED_AT\"' \
       '}' > $CURRENT_DIR/release.json \
  && if [ -d $STAGING_DIR ]; then rm -rf $BACKUP_DIR && mv $STAGING_DIR $BACKUP_DIR; fi"

# =====================================================
# Cleanup Old Images
# Keep only the running image and the backup image (also in backup/image.tar.gz).
# =====================================================
echo "========================================="
echo "Cleaning up old images"
echo "========================================="

KEEP_TAGS="$IMAGE_TAG"
[ -n "$OLD_IMAGE" ] && KEEP_TAGS="$KEEP_TAGS ${OLD_IMAGE##*:}"
remote "for t in \$(docker images '$IMAGE_NAME' --format '{{.Tag}}'); do \
  case ' $KEEP_TAGS ' in *\" \$t \"*) ;; *) docker rmi '$IMAGE_NAME':\$t || true ;; esac; done"
remote "docker images '$IMAGE_NAME'"

# =====================================================
# Show Backup
# =====================================================
echo "========================================="
echo "Current release and backup on the VM"
echo "========================================="

remote "echo '--- current/'; ls -lh $CURRENT_DIR; cat $CURRENT_DIR/release.json; \
        echo '--- backup/'; ls -lh $BACKUP_DIR 2>/dev/null && cat $BACKUP_DIR/release.json 2>/dev/null || echo '(no previous release — first deploy)'"

# =====================================================
# Result
# =====================================================
echo "========================================="
echo "Deployment complete. IMAGE_TAG=$IMAGE_TAG is live."
echo "========================================="
