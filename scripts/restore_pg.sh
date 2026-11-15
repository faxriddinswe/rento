#!/usr/bin/env bash
# Restore a pg dump into a NEW database (never overwrites): scripts/restore_pg.sh backups/pg-X.dump rento_restored
set -euo pipefail
F=${COMPOSE_FILE:-docker-compose.yml}
docker compose -f "$F" exec -T postgres createdb -U rento "$2"
docker compose -f "$F" exec -T postgres pg_restore -U rento -d "$2" < "$1"
echo "restored into $2"
