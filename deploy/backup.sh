#!/usr/bin/env bash
# Nightly backup: Postgres (online, pg_dump custom format) + Neo4j (offline dump: Neo4j Community can
# only dump a stopped database, so Neo4j pauses for the dump, typically well under a minute).
#
#   deploy/backup.sh                     # upload to R2 (needs BACKUP_R2_* in /opt/graphrecall/.env)
#   BACKUP_DEST=/tmp/drill deploy/backup.sh   # local folder instead (used by the CI restore drill)
#
# Retention: set a 14-day lifecycle rule on the R2 bucket (see RUNBOOK.md); local mode keeps the
# newest $KEEP_LOCAL backups.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMPOSE=(docker compose -f "$HERE/compose.prod.yml" --env-file "${ENV_FILE:-/opt/graphrecall/.env}")
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
NEO4J_VOLUME="${NEO4J_VOLUME:-graphrecall_neo4jdata}"

echo "[$STAMP] postgres dump"
"${COMPOSE[@]}" exec -T postgres pg_dump -U graphrecall -d graphrecall -Fc > "$WORK/postgres.dump"

echo "[$STAMP] neo4j dump (neo4j paused)"
"${COMPOSE[@]}" stop neo4j
restart_neo4j() { "${COMPOSE[@]}" start neo4j >/dev/null; }
trap 'restart_neo4j; rm -rf -- "$WORK"' EXIT
docker run --rm -v "$NEO4J_VOLUME:/data" -v "$WORK:/backups" neo4j:5-community \
  neo4j-admin database dump neo4j --to-path=/backups
restart_neo4j
trap 'rm -rf -- "$WORK"' EXIT

( cd "$WORK" && sha256sum postgres.dump neo4j.dump > SHA256SUMS )
echo "{\"stamp\": \"$STAMP\", \"postgres_bytes\": $(stat -c %s "$WORK/postgres.dump" 2>/dev/null || stat -f %z "$WORK/postgres.dump"), \"neo4j_bytes\": $(stat -c %s "$WORK/neo4j.dump" 2>/dev/null || stat -f %z "$WORK/neo4j.dump")}" > "$WORK/meta.json"

if [[ -n "${BACKUP_DEST:-}" ]]; then
  mkdir -p "$BACKUP_DEST/$STAMP"
  cp "$WORK"/* "$BACKUP_DEST/$STAMP/"
  KEEP_LOCAL="${KEEP_LOCAL:-7}"
  ls -1d "$BACKUP_DEST"/*/ 2>/dev/null | sort | head -n "-$KEEP_LOCAL" | while read -r old; do
    case "$old" in "$BACKUP_DEST"/2*) rm -rf -- "$old" ;; esac
  done
  echo "backup $STAMP written to $BACKUP_DEST/$STAMP"
else
  : "${BACKUP_R2_ENDPOINT:?}" "${BACKUP_R2_BUCKET:?}" "${BACKUP_R2_ACCESS_KEY_ID:?}" "${BACKUP_R2_SECRET_ACCESS_KEY:?}"
  docker run --rm -v "$WORK:/b:ro" \
    -e AWS_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID" -e AWS_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY" -e AWS_DEFAULT_REGION=auto \
    amazon/aws-cli s3 cp /b "s3://$BACKUP_R2_BUCKET/backups/$STAMP/" --recursive --endpoint-url "$BACKUP_R2_ENDPOINT"
  echo "backup $STAMP uploaded to r2://$BACKUP_R2_BUCKET/backups/$STAMP/"
fi
