#!/usr/bin/env bash
# Restore Postgres + Neo4j from a backup made by backup.sh. Stops api and agent-worker while it runs.
#
#   deploy/restore.sh 20261122T030000Z           # from R2
#   BACKUP_DEST=/tmp/drill deploy/restore.sh latest   # from a local folder (CI restore drill)
#
# Destructive: it replaces the current databases. Interactive runs ask for confirmation unless
# RESTORE_YES=1 (CI sets it).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE=(docker compose -f "$HERE/compose.prod.yml" --env-file "${ENV_FILE:-/opt/graphrecall/.env}")
ID="${1:?usage: restore.sh <backup-stamp|latest>}"
NEO4J_VOLUME="${NEO4J_VOLUME:-graphrecall_neo4jdata}"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

if [[ -n "${BACKUP_DEST:-}" ]]; then
  [[ "$ID" == latest ]] && ID="$(ls -1 "$BACKUP_DEST" | sort | tail -1)"
  cp "$BACKUP_DEST/$ID"/* "$WORK/"
else
  : "${R2_ENDPOINT:?}" "${R2_BUCKET:?}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}"
  AWS=(docker run --rm -v "$WORK:/b" -e AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" -e AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
       -e AWS_DEFAULT_REGION=auto amazon/aws-cli)
  if [[ "$ID" == latest ]]; then
    ID="$("${AWS[@]}" s3 ls "s3://$R2_BUCKET/backups/" --endpoint-url "$R2_ENDPOINT" | awk '{print $2}' | tr -d / | sort | tail -1)"
  fi
  "${AWS[@]}" s3 cp "s3://$R2_BUCKET/backups/$ID/" /b --recursive --endpoint-url "$R2_ENDPOINT"
fi

( cd "$WORK" && sha256sum -c SHA256SUMS )
echo "restoring backup $ID"
if [[ "${RESTORE_YES:-}" != 1 ]]; then
  read -r -p "This REPLACES the current Postgres and Neo4j data with backup $ID. Type the stamp to confirm: " ans
  [[ "$ans" == "$ID" ]] || { echo "aborted"; exit 1; }
fi

"${COMPOSE[@]}" stop api agent-worker 2>/dev/null || true

"${COMPOSE[@]}" exec -T postgres pg_restore -U graphrecall -d graphrecall --clean --if-exists --no-owner < "$WORK/postgres.dump"

"${COMPOSE[@]}" stop neo4j
docker run --rm -v "$NEO4J_VOLUME:/data" -v "$WORK:/backups:ro" neo4j:5-community \
  neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true
"${COMPOSE[@]}" start neo4j

"${COMPOSE[@]}" up -d api agent-worker 2>/dev/null || true
echo "restore of $ID complete"
