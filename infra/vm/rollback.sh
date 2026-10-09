#!/bin/bash
# =====================================================
# Sales CRM — inspect or restore the single backup kept per app.
# Installed on the VM as /opt/sales-crm/rollback.sh. Run as root or deploy.
#
#   rollback.sh status         show current release + backup for api and web
#   rollback.sh api [-y]       restore api/backup (image + api.env) as the running release
#   rollback.sh web [-y]       restore web/backup (image) as the running release
#
# Only ever touches sales-crm-* containers (the VM also runs innovault).
# The database is never touched.
# =====================================================
set -euo pipefail

ROOT=/opt/sales-crm

die() { echo "ERROR: $*" >&2; exit 1; }

json_field() {
  # $1 = file, $2 = key — tiny reader for the flat release.json files
  sed -n "s/.*\"$2\": *\"\{0,1\}\([^\",]*\)\"\{0,1\}.*/\1/p" "$1" | head -1
}

show() {
  local app=$1
  for d in current backup; do
    echo "--- $app/$d"
    if [ -d "$ROOT/$app/$d" ]; then
      ls -lh "$ROOT/$app/$d" | tail -n +2
      cat "$ROOT/$app/$d/release.json" 2>/dev/null || true
    else
      echo "(none)"
    fi
  done
  echo
}

case "${1:-status}" in
  status)
    show api
    show web
    echo "--- running containers"
    docker ps -a --filter name=sales-crm- --format '{{.Names}} → {{.Image}} ({{.Status}})'
    exit 0
    ;;
  api) APP=api; PORT=8200; HEALTH_PATH=/health ;;
  web) APP=web; PORT=3200; HEALTH_PATH=/ ;;
  *)   die "usage: $0 status | api [-y] | web [-y]" ;;
esac

NAME=sales-crm-$APP
CUR=$ROOT/$APP/current
BAK=$ROOT/$APP/backup

[ -f "$BAK/image.tar.gz" ] || die "no backup image in $BAK — nothing to roll back to"
[ -f "$BAK/release.json" ] || die "no $BAK/release.json"
[ "$APP" = web ] || [ -f "$BAK/api.env" ] || die "no $BAK/api.env"

BACKUP_IMAGE=$(json_field "$BAK/release.json" image)
[[ "$BACKUP_IMAGE" =~ ^$NAME:[0-9]+$ ]] || die "backup image '$BACKUP_IMAGE' is not a $NAME image"
RUNNING_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$NAME" 2>/dev/null || true)

echo "App:            $APP"
echo "Running now:    ${RUNNING_IMAGE:-<nothing>}"
echo "Restore backup: $BACKUP_IMAGE (build $(json_field "$BAK/release.json" build), deployed $(json_field "$BAK/release.json" deployed_at))"
if [ "${2:-}" != "-y" ]; then
  read -r -p "Proceed? [y/N] " ans
  [ "$ans" = y ] || [ "$ans" = Y ] || die "aborted"
fi

run() {
  # $1 = image, $2 = env file (api only) — same settings as deploy.sh
  docker stop "$NAME" >/dev/null 2>&1 || true
  docker rm "$NAME" >/dev/null 2>&1 || true
  if [ "$APP" = api ]; then
    docker run -d --name "$NAME" --network sales-crm-net -p 127.0.0.1:$PORT:8000 --env-file "$2" \
      -v "$ROOT/media:/app/media" --memory=768m \
      --log-opt max-size=10m --log-opt max-file=3 --restart unless-stopped \
      "$1" uvicorn app.main:app --host 0.0.0.0 --port 8000 >/dev/null
  else
    docker run -d --name "$NAME" -p 127.0.0.1:$PORT:80 --memory=128m \
      --log-opt max-size=10m --log-opt max-file=3 --restart unless-stopped \
      "$1" >/dev/null
  fi
}

healthy() {
  for _ in $(seq 1 40); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT$HEALTH_PATH" || true)" = 200 ] && return 0
    sleep 5
  done
  return 1
}

if ! docker image inspect "$BACKUP_IMAGE" >/dev/null 2>&1; then
  echo "Loading $BACKUP_IMAGE from $BAK/image.tar.gz ..."
  gunzip -c "$BAK/image.tar.gz" | docker load
fi

echo "Starting $BACKUP_IMAGE ..."
run "$BACKUP_IMAGE" "$BAK/api.env"

if healthy; then
  cp "$BAK/release.json" "$CUR/release.json"
  [ "$APP" = web ] || cp -p "$BAK/api.env" "$CUR/api.env"
  [ "$(id -u)" = 0 ] && chown -R deploy:deploy "$ROOT/$APP"
  echo "OK — $NAME is running $BACKUP_IMAGE and is healthy. The database was not touched."
else
  echo "ERROR: $BACKUP_IMAGE did not become healthy — logs:"
  docker logs --tail 30 "$NAME" || true
  if [ -n "$RUNNING_IMAGE" ]; then
    echo "Restarting the previous image $RUNNING_IMAGE ..."
    run "$RUNNING_IMAGE" "$CUR/api.env"
    healthy && echo "Previous image is running again." || echo "Previous image is NOT healthy either — manual intervention required."
  fi
  exit 1
fi
