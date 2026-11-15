#!/usr/bin/env bash
# Deploy to the shared VPS. Needs .env.deploy (DEPLOY_HOST DEPLOY_USER SSH_KEY_PATH BASE_DOMAIN SUBDOMAIN) and .env.prod.
set -euo pipefail
[ -f .env.deploy ] || { echo "No .env.deploy -> see docs/BLOCKERS.md"; exit 1; }
set -a; . ./.env.deploy; set +a
SSH="ssh -i $SSH_KEY_PATH $DEPLOY_USER@$DEPLOY_HOST"
HOST="$SUBDOMAIN.$BASE_DOMAIN"; FILES="$SUBDOMAIN-files.$BASE_DOMAIN"
echo "== preflight"; $SSH 'df -h / | tail -1; free -m | sed -n 2p; ss -ltn | grep -E ":(80|443) " || true; docker --version'
rsync -az --delete -e "ssh -i $SSH_KEY_PATH" --exclude node_modules --exclude .venv --exclude .git --exclude .env --exclude backups ./ "$DEPLOY_USER@$DEPLOY_HOST:/opt/rento/"
scp -i "$SSH_KEY_PATH" .env.prod "$DEPLOY_USER@$DEPLOY_HOST:/opt/rento/.env.prod"
$SSH "cd /opt/rento && set -a && . ./.env.prod && set +a && docker compose -f docker-compose.prod.yml up -d --build && \
  sed -e 's/{\$RENTO_HOST}/$HOST/' -e 's/{\$RENTO_FILES_HOST}/$FILES/' deploy/rento.caddy > /opt/edge/sites/rento.caddy && \
  docker exec edge-caddy-1 caddy reload --config /etc/caddy/Caddyfile || true"
echo "== smoke"; curl -fsS "https://$HOST/api/ready"
