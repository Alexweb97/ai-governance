"""Fonctions communes aux hooks de gouvernance Claude Code (stdlib uniquement)."""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# pii.py est copié à côté des hooks par install.sh ; en dev on le prend dans le dépôt.
for candidate in (HERE, HERE.parent / "proxy" / "app"):
    if (candidate / "pii.py").exists():
        sys.path.insert(0, str(candidate))
        break

from pii import Detector, apply_overrides, load_json, load_terms, with_terms  # noqa: E402

POLICY_PATH = os.environ.get("CLAUDE_GOV_POLICY", "/opt/claude-governance/policy/policy.json")
# Dictionnaire et réglages écrits par la console d'administration (dossier interdit à Claude).
CONFIG_DIR = Path(os.environ.get("CLAUDE_GOV_CONFIG_DIR") or Path.home() / ".config" / "claude-governance")
TERMS_PATH = os.environ.get("CLAUDE_GOV_TERMS", str(CONFIG_DIR / "terms.json"))
OVERRIDES_PATH = CONFIG_DIR / "overrides.json"
C3_SESSIONS_PATH = CONFIG_DIR / "c3-sessions.json"
C3_PATHS_PATH = CONFIG_DIR / "c3-paths.json"  # chemins C3 déclarés dans la console (écran Projets)


def c3_paths() -> list[str]:
    """Chemins absolus déclarés C3. Fichier absent : aucun. Fichier illisible : exception (fail-closed)."""
    data = load_json(C3_PATHS_PATH, {})
    return [os.path.normpath(p) for p in data.get("paths", []) if isinstance(p, str) and os.path.isabs(p)]


def load_policy() -> dict:
    with open(POLICY_PATH, encoding="utf-8") as f:
        return apply_overrides(json.load(f), load_json(OVERRIDES_PATH, {}))


def read_input() -> dict:
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def provider() -> str:
    """Fournisseur de modèle choisi dans la console : "claude" (défaut) ou "trusted"."""
    try:
        return load_json(OVERRIDES_PATH, {}).get("provider", "claude")
    except ValueError:
        return "claude"


def provider_label() -> str:
    """Nom affiché du fournisseur de confiance (écrit par la console à la bascule)."""
    try:
        return str(load_json(OVERRIDES_PATH, {}).get("provider_label") or "Fournisseur de confiance")
    except ValueError:
        return "Fournisseur de confiance"


def update_c3_sessions(fn) -> None:
    """Modifie le registre des sessions C3 sous verrou (plusieurs hooks peuvent tourner en parallèle)."""
    import fcntl
    import tempfile

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_DIR / ".c3.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = load_json(C3_SESSIONS_PATH, {})
        except ValueError:
            data = {}
        fn(data)
        fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".c3-sessions.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, C3_SESSIONS_PATH)


def mark_c3_session(session_id: str, cwd: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def fn(data: dict) -> None:
        s = data.setdefault(session_id, {"opened": now, "cwd": cwd, "accesses": 0, "ended": None})
        s["last"] = now
        s["accesses"] = s.get("accesses", 0) + 1
        s["ended"] = None  # une session reprise redevient ouverte
    update_c3_sessions(fn)


def end_c3_session(session_id: str) -> None:
    if not session_id or not C3_SESSIONS_PATH.exists():
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def fn(data: dict) -> None:
        if session_id in data:
            data[session_id]["ended"] = now
    update_c3_sessions(fn)


def detector(policy: dict) -> Detector:
    return Detector(with_terms(policy.get("pii", {}), load_terms(TERMS_PATH)))


def redact(text: str, det: Detector) -> str:
    """Masquage irréversible pour les journaux : valeur -> [TYPE]."""
    spans = det.detect(text)
    out, pos = [], 0
    for s in spans:
        out.append(text[pos:s.start])
        out.append(f"[{s.type}]")
        pos = s.end
    out.append(text[pos:])
    return "".join(out)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def audit(policy: dict, record: dict) -> None:
    path = os.environ.get("CLAUDE_GOV_AUDIT_LOG") or policy.get("audit", {}).get(
        "hooks_log", "/var/log/claude-governance/hooks-audit.jsonl")
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "component": "hook",
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        **record,
    }
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        from messages import prefixed, t
        print(prefixed(t("audit_write_error", path=path, error=e)), file=sys.stderr)


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)


def fail_mode(policy: dict | None) -> str:
    try:
        return (policy or load_policy()).get("hooks", {}).get("fail_mode", "closed")
    except Exception:
        return "closed"
