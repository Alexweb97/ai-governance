#!/usr/bin/env bash
# Installation de la console de gouvernance Claude Code sous WSL Ubuntu.
#   ./install.sh            installation complète
#   ./install.sh --no-stack hooks + managed-settings uniquement (sans Docker)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=/opt/claude-governance
MANAGED_DIR=/etc/claude-code
LOG_DIR=/var/log/claude-governance
CONFIG_DIR="$HOME/.config/claude-governance"   # dictionnaire + réglages (écrits par la console)
CLIENTS_DIR="$HOME/clients"
WITH_STACK=1
[[ "${1:-}" == "--no-stack" ]] && WITH_STACK=0

info()  { printf '\033[1;34m[gouvernance]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[attention]\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m[erreur]\033[0m %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ prérequis
command -v python3 >/dev/null || die "python3 requis"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "python3 >= 3.9 requis"
command -v claude >/dev/null || warn "Claude Code introuvable dans le PATH (installation possible plus tard)"
if ! command -v pdftotext >/dev/null || ! command -v ocrmypdf >/dev/null; then
  info "Installation de pdftotext et de l'OCR français : les PDF (y compris scannés) sont lus en texte pour être pseudonymisés"
  sudo apt-get install -y poppler-utils ocrmypdf tesseract-ocr-fra >/dev/null \
    || warn "poppler-utils / ocrmypdf non installés : Claude ne pourra pas lire les PDF"
fi
if (( WITH_STACK )); then
  command -v docker >/dev/null || die "Docker requis (Docker Desktop avec intégration WSL, ou docker-ce dans WSL)"
  docker compose version >/dev/null 2>&1 || die "Plugin 'docker compose' requis"
fi
sudo -v || die "Droits sudo nécessaires pour /opt, /etc/claude-code et /var/log"

# ------------------------------------------------------------------ secrets (.env)
if [[ ! -f "$REPO/.env" ]]; then
  info "Génération de .env (secret de pseudonymisation + mot de passe Grafana)"
  umask 077
  cat > "$REPO/.env" <<EOF
PSEUDO_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
GRAFANA_ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
HOST_UID=$(id -u)
HOST_GID=$(id -g)
GOV_LOG_DIR=$LOG_DIR
EOF
  umask 022
else
  info ".env existant conservé"
fi
# Variables ajoutées avec la console d'administration (complète un .env plus ancien)
add_env() { grep -q "^$1=" "$REPO/.env" || echo "$1=$2" >> "$REPO/.env"; }
add_env ADMIN_PASSWORD "$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
add_env GOV_CONFIG_DIR "$CONFIG_DIR"
add_env CLIENTS_DIR "$CLIENTS_DIR"
add_env GRAFANA_PORT 3001
add_env PROJECTS_DIR "$HOME/project"   # projets de code déclarables dans la console (montés en lecture seule)

# ------------------------------------------------------------------ dossiers de la console
install -d -m 700 "$CONFIG_DIR"
install -d -m 755 "$CLIENTS_DIR"
install -d -m 755 "$HOME/project"
if [[ -f "$REPO/policy/terms.json" && ! -f "$CONFIG_DIR/terms.json" ]]; then
  info "Reprise de policy/terms.json dans $CONFIG_DIR (géré désormais par la console)"
  install -m 600 "$REPO/policy/terms.json" "$CONFIG_DIR/terms.json"
fi

# ------------------------------------------------------------------ hooks + politique
info "Installation des hooks et de la politique dans $PREFIX (propriétaire root, lecture seule)"
sudo install -d -m 755 "$PREFIX/hooks" "$PREFIX/policy"
sudo install -m 644 "$REPO/proxy/app/pii.py" "$PREFIX/hooks/pii.py"
sudo install -m 644 "$REPO/hooks/common.py" "$PREFIX/hooks/common.py"
for h in guard_prompt guard_tool audit statusline; do
  sudo install -m 755 "$REPO/hooks/$h.py" "$PREFIX/hooks/$h.py"
done
sudo install -m 644 "$REPO/policy/policy.json" "$PREFIX/policy/policy.json"

# ------------------------------------------------------------------ journaux d'audit
info "Création de $LOG_DIR"
sudo install -d -m 755 -o "$(id -u)" -g "$(id -g)" "$LOG_DIR"
touch "$LOG_DIR/hooks-audit.jsonl" "$LOG_DIR/proxy-audit.jsonl"
chmod 644 "$LOG_DIR"/*.jsonl
if [[ -d /etc/logrotate.d ]]; then
  sudo tee /etc/logrotate.d/claude-governance >/dev/null <<EOF
$LOG_DIR/*.jsonl {
  weekly
  rotate 12
  compress
  missingok
  notifempty
  copytruncate
}
EOF
fi

# ------------------------------------------------------------------ smoke test des hooks
info "Test des hooks"
export CLAUDE_GOV_AUDIT_LOG=/tmp/claude-gov-install-test.jsonl
out=$(echo '{"tool_name":"Read","tool_input":{"file_path":".env"},"cwd":"/tmp"}' | python3 "$PREFIX/hooks/guard_tool.py")
grep -q '"deny"' <<<"$out" || die "guard_tool ne refuse pas la lecture de .env : $out"
out=$(echo '{"prompt":"ma clé sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"}' | python3 "$PREFIX/hooks/guard_prompt.py")
grep -q '"block"' <<<"$out" || die "guard_prompt ne bloque pas une clé API : $out"
rm -f "$CLAUDE_GOV_AUDIT_LOG"; unset CLAUDE_GOV_AUDIT_LOG
info "Hooks OK"

# ------------------------------------------------------------------ stack Docker
if (( WITH_STACK )); then
  # Proxy TLS d'entreprise (Zscaler...) : les conteneurs doivent faire confiance aux mêmes autorités
  # que le poste, sinon pip, le téléchargement du modèle et l'appel à l'API échouent.
  install -d "$REPO/certs"
  if compgen -G "/usr/local/share/ca-certificates/*.crt" >/dev/null; then
    cp /usr/local/share/ca-certificates/*.crt "$REPO/certs/"
    info "Certificats d'entreprise ajoutés aux images : $(cd "$REPO/certs" && ls *.crt | tr '\n' ' ')"
  fi
  set -a; source "$REPO/.env"; set +a
  # Ports publiés par nos propres conteneurs (plages comprises : 4317-4318->4317-4318)
  ours=$(docker ps --filter label=com.docker.compose.project=claude-governance --format '{{.Ports}}' | python3 -c '
import re, sys
for a, b in re.findall(r":(\d+)(?:-(\d+))?->", sys.stdin.read()):
    print(*range(int(a), int(b or a) + 1))')
  for port in 8787 8788 "${GRAFANA_PORT:-3001}" 9090 4317 4318; do
    if ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN && ! grep -qw "$port" <<<"$ours"; then
      die "Le port $port est déjà utilisé par un autre programme. Changez-le dans .env (ex. GRAFANA_PORT=3002) ou arrêtez ce programme."
    fi
  done
  info "Construction et démarrage de la stack (le premier build de Presidio télécharge ~600 Mo)"
  (cd "$REPO" && docker compose up -d --build)
  info "Attente du proxy (Presidio peut mettre 1 à 2 min à charger le modèle français)..."
  for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8787/healthz >/dev/null 2>&1; then ok=1; break; fi
    sleep 5
  done
  [[ "${ok:-0}" == 1 ]] || die "Le proxy ne répond pas. Voir : docker compose logs proxy presidio"
  info "Proxy OK : $(curl -fsS http://127.0.0.1:8787/healthz)"
fi

# ------------------------------------------------------------------ managed settings (en dernier)
# En dernier : dès que ce fichier existe, Claude Code passe par le proxy.
info "Déploiement de $MANAGED_DIR/managed-settings.json"
sudo install -d -m 755 "$MANAGED_DIR"
if [[ -f "$MANAGED_DIR/managed-settings.json" ]]; then
  sudo cp "$MANAGED_DIR/managed-settings.json" "$MANAGED_DIR/managed-settings.json.bak.$(date +%s)"
fi
src="$REPO/claude/managed-settings.json"
if (( ! WITH_STACK )); then
  warn "--no-stack : ANTHROPIC_BASE_URL et la télémétrie OTel ne sont pas activés"
  tmp=$(mktemp)
  python3 - "$src" "$tmp" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
for k in [k for k in s.get("env", {}) if k == "ANTHROPIC_BASE_URL" or k.startswith("OTEL_") or k == "CLAUDE_CODE_ENABLE_TELEMETRY"]:
    s["env"].pop(k)
json.dump(s, open(sys.argv[2], "w"), indent=2)
PY
  src="$tmp"
fi
sudo install -m 644 "$src" "$MANAGED_DIR/managed-settings.json"

cat <<EOF

  Installation terminée.

  Console admin   : http://localhost:8788   (admin / ADMIN_PASSWORD dans $REPO/.env)
  Console Grafana : http://localhost:${GRAFANA_PORT:-3001}   (admin / GRAFANA_ADMIN_PASSWORD dans $REPO/.env)
  Proxy           : http://127.0.0.1:8787/healthz
  Prometheus      : http://localhost:9090
  Audit (fichiers): $LOG_DIR/

  Vérifiez dans Claude Code :  /status  -> "Setting sources" doit mentionner les managed settings.
  Tests de bout en bout :      ./scripts/smoke-test.sh

EOF
