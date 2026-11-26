#!/usr/bin/env bash
# Tests de bout en bout une fois la stack démarrée.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
MODEL="${SMOKE_MODEL:-claude-haiku-5-5}"
pass=0; fail=0
ok()  { printf '  \033[32m✔\033[0m %s\n' "$*"; pass=$((pass+1)); }
ko()  { printf '  \033[31m✘\033[0m %s\n' "$*"; fail=$((fail+1)); }

echo "1. Santé des services"
h=$(curl -fsS http://127.0.0.1:8787/healthz 2>/dev/null) && ok "proxy : $h" || ko "proxy injoignable"
curl -fsS http://127.0.0.1:${GRAFANA_PORT:-3001}/api/health >/dev/null 2>&1 && ok "grafana" || ko "grafana"
curl -fsS http://127.0.0.1:9090/-/ready >/dev/null 2>&1 && ok "prometheus" || ko "prometheus"
c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8788/api/clients); p=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8788/); [[ "$c" == 401 && "$p" == 200 ]] && ok "console admin (interface servie, API protégée)" || ko "console admin : page $p, API $c"

echo "2. Presidio (NER français) via le réseau Docker"
r=$(docker compose exec -T proxy python -c "
import httpx; print(httpx.post('http://presidio:3000/analyze', json={'text':'Bonjour, je suis Marie Dupont et j habite à Lyon.','language':'fr'}).text)" 2>&1)
grep -q PERSON <<<"$r" && ok "PERSON détecté" || ko "Presidio fr : $r"

echo "3. Pseudonymisation de bout en bout (nécessite ANTHROPIC_API_KEY ou une session Claude Code)"
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  resp=$(curl -sS http://127.0.0.1:8787/v1/messages \
    -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
    -d '{"model":"'"$MODEL"'","max_tokens":200,"messages":[{"role":"user","content":"Répète exactement, sans rien ajouter : jean.martin@acme.fr / FR76 3000 6000 0112 3456 7890 189"}]}')
  grep -q "jean.martin@acme.fr" <<<"$resp" && ok "réponse ré-identifiée (valeur réelle restituée)" || ko "ré-identification : $resp"
  tail -n 5 /var/log/claude-governance/proxy-audit.jsonl | grep -q pii_pseudonymized && ok "audit proxy écrit" || ko "pas d'audit proxy"
else
  echo "  (ignoré : exportez ANTHROPIC_API_KEY pour ce test)"
fi

echo "4. Guardrails"
t=$(echo '{"tool_name":"Bash","tool_input":{"command":"psql -c \"DELETE FROM orders\""},"cwd":"/tmp"}' | python3 /opt/claude-governance/hooks/guard_tool.py)
grep -q deny <<<"$t" && ok "DELETE sans WHERE refusé" || ko "DELETE sans WHERE : $t"
t=$(echo '{"tool_name":"Bash","tool_input":{"command":"cat ~/.ssh/id_rsa"},"cwd":"/tmp"}' | python3 /opt/claude-governance/hooks/guard_tool.py)
grep -q deny <<<"$t" && ok "lecture clé SSH refusée" || ko "clé SSH : $t"

echo; echo "Résultat : $pass OK, $fail KO"
exit $(( fail > 0 ))
