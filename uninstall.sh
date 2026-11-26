#!/usr/bin/env bash
# Désinstallation. Les journaux d'audit et les volumes Docker sont conservés
# sauf avec --purge.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[gouvernance] Retrait des managed settings (Claude Code reprend l'accès direct à l'API)"
sudo rm -f /etc/claude-code/managed-settings.json
sudo rm -rf /opt/claude-governance
sudo rm -f /etc/logrotate.d/claude-governance

if [[ "${1:-}" == "--purge" ]]; then
  (cd "$REPO" && docker compose down -v) || true
  sudo rm -rf /var/log/claude-governance
  rm -f "$REPO/.env"
else
  (cd "$REPO" && docker compose down) || true
  echo "[gouvernance] Journaux conservés dans /var/log/claude-governance (--purge pour tout supprimer)"
fi
