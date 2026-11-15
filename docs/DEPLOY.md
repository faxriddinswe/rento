# Deploy
Target: one shared VPS with edge Caddy in `/opt/edge` (network `edge`, `import /opt/edge/sites/*.caddy`). Rento joins that network; no host ports are published.
1. Fill `.env.deploy` and `.env.prod` (see BLOCKERS #2). 2. `scripts/deploy.sh` (preflight → rsync → `docker compose -f docker-compose.prod.yml up -d --build` → writes `/opt/edge/sites/rento.caddy` → reload → smoke `GET https://<host>/api/ready`).
Memory limits: api 384m, worker 320m, postgres 384m, redis 128m, minio 192m, frontend 192m (tune after measuring PDF memory).
Rollback: `git checkout <prev> && scripts/deploy.sh`; DB: restore with `scripts/restore_pg.sh`. Status: **not deployed** (no `.env.deploy`).
