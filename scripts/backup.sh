#!/usr/bin/env bash
# Nightly backup: pg_dump + MinIO data tarball, keep 7. Usage: scripts/backup.sh [compose-file]
set -euo pipefail
F=${1:-docker-compose.yml}; D=${BACKUP_DIR:-backups}; TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$D"
docker compose -f "$F" exec -T postgres pg_dump -U rento -Fc rento > "$D/pg-$TS.dump"
P=${COMPOSE_PROJECT_NAME:-rento-dev}
docker run --rm -v "${P}_miniodata:/data:ro" -v "$PWD/$D:/backup" alpine tar czf "/backup/minio-$TS.tgz" -C /data .
ls -1t "$D"/pg-*.dump | tail -n +8 | xargs -r rm --
ls -1t "$D"/minio-*.tgz 2>/dev/null | tail -n +8 | xargs -r rm --
echo "backup ok: $D/pg-$TS.dump"
