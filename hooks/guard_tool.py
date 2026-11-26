#!/usr/bin/env python3
"""
Hook PreToolUse : guardrails sur chaque action de Claude Code avant exécution.

Décisions possibles (renvoyées à Claude Code) :
  deny -> action refusée, la raison est montrée à Claude qui adapte son plan ;
  ask  -> l'utilisateur doit confirmer explicitement ;
  (rien) -> flux normal des permissions.

Règles (policy.json > tool_guard) :
  - fichiers sensibles (.env, clés, ~/.ssh, tfstate...) en lecture/écriture/recherche/Bash ;
  - niveau C3 (_confidentiel/, *.confidentiel.*) : lisible uniquement quand le fournisseur de
    confiance est actif ; la session est alors marquée C3 (le proxy ne l'enverra jamais à Anthropic) ;
  - lecture directe de PDF et d'images (non pseudonymisables) : deny, avec renvoi vers pdftotext ;
  - commandes Bash dangereuses ou d'exfiltration (deny) / à confirmer (ask) ;
  - commande réseau contenant un secret (deny) ou une PII (ask par défaut) ;
  - SQL destructif (DROP, TRUNCATE, DELETE/UPDATE sans WHERE...) dans Bash et les outils MCP ;
  - requêtes sur des tables contenant des données personnelles (ask) ;
  - secret écrit en dur dans un fichier (ask) ;
  - WebFetch vers des domaines d'exfiltration connus (deny).
"""
from __future__ import annotations

import glob
import os
import re
import shlex
import sys
import time
from fnmatch import fnmatch
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from messages import policy_text, prefixed, rule_reason, set_language, t
from common import (audit, c3_paths, detector, emit, fail_mode, load_policy, mark_c3_session, provider,
                    read_input, redact)

Decision = Optional[tuple[str, str, str]]  # (decision, raison, règle)

FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead"}
SEARCH_TOOLS = {"Grep", "Glob", "LS"}
_DML_RE = re.compile(r"(?is)\b(DELETE\s+FROM|UPDATE\s+[\w.\"`\[\]]+\s+SET)\b[^;]*")
# Fragments d'un mot shell pouvant être un chemin : isole ".env" dans "<.env",
# "open('.env')" ou "$(echo .env)".
_PATH_FRAGMENT_RE = re.compile(r"[\w./~*?\[\]$-]+")
_GLOB_CHARS = set("*?[")
_MAX_GLOB_MATCHES = 200


# ----------------------------------------------------------------------------- utilitaires
def _strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _abs(path: str, cwd: str) -> str:
    p = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return os.path.normpath(p)


def sensitive_path(path: str, cwd: str, cfg: dict) -> Optional[str]:
    if not path:
        return None
    ap = _abs(path, cwd)
    if os.path.basename(ap) in set(cfg.get("sensitive_path_exceptions", [])):
        return None
    for pat in cfg.get("sensitive_paths", []):
        if fnmatch(ap, pat) or fnmatch(ap.rstrip("/") + "/", pat):
            return pat
    return None


def _command_paths(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    out = []
    for t in tokens:
        for part in _PATH_FRAGMENT_RE.findall(t):
            if part and not part.startswith("-") and ("/" in part or "." in part or part.startswith("~")):
                out.append(part)
    return out


def _glob_matches(path: str, cwd: str) -> list[str]:
    """Fichiers réels désignés par un motif shell (cat .en?, cat secrets/*)."""
    if not _GLOB_CHARS & set(path):
        return []
    return glob.glob(_abs(path, cwd))[:_MAX_GLOB_MATCHES]


def check_network_pii(command: str, cfg: dict, policy: dict) -> Decision:
    """Commande réseau contenant une valeur sensible (ex. ré-identifiée par le proxy)."""
    net = cfg.get("bash_network_regex")
    if not net or not re.search(net, command):
        return None
    types = sorted({s.type for s in detector(policy).detect(command)})
    if not types:
        return None
    if any(t.startswith("SECRET_") for t in types):
        return "deny", t("network_secret", types=", ".join(types)), "bash_network_pii"
    return (cfg.get("bash_network_pii_decision", "ask"),
            t("network_pii", types=", ".join(types)), "bash_network_pii")


def check_sql(text: str, cfg: dict) -> Decision:
    for rule in cfg.get("sql_deny", []):
        if re.search(rule["regex"], text):
            return "deny", rule_reason(rule), "sql_deny"
    if cfg.get("sql_deny_dml_without_where", True):
        for m in _DML_RE.finditer(text):
            stmt = m.group(0)
            # on s'arrête à la fin probable de la chaîne SQL dans une commande shell
            stmt = re.split(r"[\"'`]\s*(?:$|[|&;])", stmt)[0]
            if not re.search(r"(?i)\bWHERE\b", stmt):
                return "deny", t("dml_without_where", verb=m.group(1).split()[0].upper()), "sql_dml_without_where"
    tables = cfg.get("pii_tables", [])
    if tables:
        names = "|".join(re.escape(t) for t in tables)
        pat = rf"(?i)\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:[\w\"`\[\]]+\.)*[\"`\[]?(?:{names})[\"`\]]?\b"
        m = re.search(pat, text)
        if m:
            return (cfg.get("pii_tables_decision", "ask"),
                    t("pii_table", table=m.group(0).split()[-1]),
                    "pii_tables")
    return None


# ----------------------------------------------------------------------------- règles par outil
def check_bash(command: str, cwd: str, cfg: dict, policy: dict) -> Decision:
    for rule in cfg.get("bash_deny", []):
        if re.search(rule["regex"], command):
            return "deny", rule_reason(rule), "bash_deny"
    for p in _command_paths(command):
        for candidate in [p, *_glob_matches(p, cwd)]:
            pat = sensitive_path(candidate, cwd, cfg)
            if pat:
                return "deny", t("sensitive_path_bash", path=p, pattern=pat), "sensitive_paths"
    net = check_network_pii(command, cfg, policy)
    if net:
        return net
    sql = check_sql(command, cfg)
    if sql:
        return sql
    for rule in cfg.get("bash_ask", []):
        if re.search(rule["regex"], command):
            return "ask", rule_reason(rule), "bash_ask"
    return None


def evaluate(tool: str, tin: dict, cwd: str, policy: dict) -> Decision:
    cfg = policy.get("tool_guard", {})

    if tool == "Bash":
        return check_bash(tin.get("command", "") or "", cwd, cfg, policy)

    if tool in FILE_TOOLS:
        path = tin.get("file_path") or tin.get("notebook_path") or ""
        pat = sensitive_path(path, cwd, cfg)
        if pat:
            return "deny", t("sensitive_path", path=path, pattern=pat), "sensitive_paths"
        if tool == "Read" and path.lower().endswith(tuple(cfg.get("read_media_extensions", []))):
            return "deny", policy_text(cfg, "read_media_reason", t("media")), "read_media"
        if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
            written = "\n".join(_strings({k: v for k, v in tin.items()
                                          if k in ("content", "new_string", "edits", "new_source")}))
            secrets = sorted({s.type for s in detector(policy).detect(written) if s.type.startswith("SECRET_")})
            if secrets:
                return (cfg.get("write_secret_decision", "ask"),
                        t("write_secret", file=os.path.basename(path), types=", ".join(secrets)),
                        "write_secret")
        return None

    if tool in SEARCH_TOOLS:
        for key in ("path", "pattern"):
            v = tin.get(key)
            if isinstance(v, str) and ("/" in v or v.startswith(".")):
                pat = sensitive_path(v, cwd, cfg)
                if pat:
                    return "deny", t("sensitive_search", path=v), "sensitive_paths"
        return None

    if tool == "WebFetch":
        host = (urlparse(tin.get("url", "")).hostname or "").lower()
        for d in cfg.get("web_deny_domains", []):
            if host == d or host.endswith("." + d):
                return "deny", t("web_domain", host=host), "web_deny_domains"
        types = sorted({s.type for s in detector(policy).detect(tin.get("url", ""))})
        if types:
            return "deny", t("web_url_pii", types=", ".join(types)), "web_url_pii"
        return None

    if tool.startswith("mcp__"):
        text = "\n".join(_strings(tin))
        return check_sql(text, cfg)

    return None


# Commandes qui lisent le contenu d'un dossier récursivement : viser un dossier parent d'un
# emplacement C3 suffit alors à lire du C3 (grep -r motif . depuis la racine d'un projet).
_RECURSIVE_RE = re.compile(
    r"\b[ezf]?grep\b[^|;&]*?\s-[A-Za-z]*[rR]|--recursive\b|\b(?:rg|ag|ack|tar|zip|rsync|find)\b"
    r"|\bcp\b[^|;&]*?\s-[A-Za-z]*[rRa]|\bgit\s+(?:grep|add)\b")
_WALK_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
_WALK_LIMIT = 20000  # entrées examinées au plus pour chercher un marqueur C3 sous un dossier
_WALK_SECONDS = 0.6  # et durée maximale (disque WSL lent) : au-delà, on ne conclut pas


def _inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def _forms(path: str) -> set[str]:
    return {path, os.path.realpath(path)}


def _shell_words(command: str) -> list[str]:
    """Tous les mots d'une commande pouvant désigner un fichier (y compris « config », sans / ni .)."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    return [part for t in tokens for part in _PATH_FRAGMENT_RE.findall(t) if part and not part.startswith("-")]


_CD_RE = re.compile(r"(?:^|[;&|(]\s*)(?:cd|pushd)\s+([^\s;&|)]+)")


def _shell_bases(command: str, cwd: str) -> list[str]:
    """Répertoire de travail, puis ceux atteints par les « cd » de la commande (cd x && cat y)."""
    bases, cur = [cwd], cwd
    for m in _CD_RE.finditer(command):
        cur = _abs(m.group(1).strip("'\""), cur)
        bases.append(cur)
    return bases


def _c3_targets(tool: str, tin: dict, cwd: str) -> tuple[list[str], list[str]]:
    """(chemins absolus visés directement, dossiers absolus parcourus récursivement) par l'action."""
    if tool in FILE_TOOLS:
        p = tin.get("file_path") or tin.get("notebook_path") or ""
        return ([_abs(p, cwd)] if p else []), []
    if tool == "Grep":
        p = _abs(tin.get("path") or cwd, cwd)
        return ([], [p]) if os.path.isdir(p) else ([p], [])
    if tool in ("Glob", "LS"):  # noms de fichiers seulement
        out = [_abs(tin.get("path") or cwd, cwd)]
        if tin.get("pattern"):
            out.append(_abs(tin["pattern"], out[0]))
        return out, []
    if tool == "Bash":
        command = tin.get("command", "") or ""
        words = _shell_words(command)
        paths: list[str] = []
        for base in _shell_bases(command, cwd):
            paths += [_abs(w, base) for w in words]
            paths += [m for w in words for m in _glob_matches(w, base)]
        recursive: list[str] = []
        if _RECURSIVE_RE.search(command):
            recursive = [p for p in paths if os.path.isdir(p)] or _shell_bases(command, cwd)[-1:]
        return paths, recursive
    return [_abs(s, cwd) for s in _strings(tin) if s.startswith(("/", "~/"))], []  # MCP et autres outils


def _marker_below(directory: str, marker: re.Pattern) -> Optional[bool]:
    """Un dossier ou fichier marqué C3 existe-t-il sous directory ? None : trop gros pour conclure."""
    if not os.path.isdir(directory):
        return False
    seen, deadline = 0, time.monotonic() + _WALK_SECONDS
    for _cur, dirs, files in os.walk(directory):
        if any(marker.search(n) for n in dirs + files):
            return True
        dirs[:] = [d for d in dirs if d not in _WALK_SKIP]
        seen += len(dirs) + len(files)
        if seen > _WALK_LIMIT or time.monotonic() > deadline:
            return None
    return False


def c3_access(tool: str, tin: dict, cfg: dict, cwd: str = "") -> Optional[str]:
    """L'action touche-t-elle un emplacement C3 ? "c3" : oui ; "unknown" : recherche récursive trop
    large pour le vérifier ; None : non. Emplacements C3 : marqueur de policy.json (dans n'importe quel
    texte de l'action) et chemins déclarés dans la console (c3-paths.json)."""
    marker = cfg.get("c3_marker_regex")
    if marker and any(re.search(marker, s) for s in _strings(tin)):
        return "c3"
    declared = c3_paths()
    direct, recursive = _c3_targets(tool, tin, cwd)
    for path in direct:
        if any(_inside(a, d) for a in _forms(path) for d in declared):
            return "c3"
    for path in dict.fromkeys(recursive):
        if any(_inside(a, d) or _inside(d, a) for a in _forms(path) for d in declared):
            return "c3"
        if marker:
            below = _marker_below(path, re.compile(marker))
            if below:
                return "c3"
            if below is None:
                return "unknown"
    return None




# ----------------------------------------------------------------------------- point d'entrée
def summarize(tool: str, tin: dict, policy: dict) -> str:
    max_chars = int(policy.get("audit", {}).get("max_command_chars", 300))
    if tool == "Bash":
        s = tin.get("command", "")
    elif tool in FILE_TOOLS:
        s = tin.get("file_path") or tin.get("notebook_path") or ""
    elif tool == "WebFetch":
        s = tin.get("url", "")
    else:
        s = ", ".join(sorted(tin.keys())) if isinstance(tin, dict) else ""
    return redact(str(s), detector(policy))[:max_chars]


def main() -> None:
    policy = load_policy()
    set_language(policy)
    data = read_input()
    tool = data.get("tool_name", "")
    tin = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()

    c3 = c3_access(tool, tin, policy.get("tool_guard", {}), cwd)
    if c3 and provider() != "trusted":
        result: Decision = (("deny", t("c3_denied"), "c3_requires_trusted") if c3 == "c3" else
                            ("deny", t("c3_unknown"), "c3_search_too_wide"))
    else:
        if c3:
            mark_c3_session(data.get("session_id") or "inconnue", cwd)
        result = evaluate(tool, tin, cwd, policy)
    record = {
        "event": "PreToolUse",
        "session_id": data.get("session_id"),
        "cwd": cwd,
        "tool_name": tool,
        "target": summarize(tool, tin, policy),
        "permission_mode": data.get("permission_mode"),
        **({"c3": True, "provider": "trusted"} if c3 and provider() == "trusted" else {}),
    }
    if result is None:
        audit(policy, {**record, "decision": "pass"})
        sys.exit(0)

    decision, reason, rule = result
    audit(policy, {**record, "decision": decision, "rule": rule, "reason": reason})
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": prefixed(reason),
        }
    })


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # pragma: no cover
        try:
            set_language(load_policy())
        except Exception:
            pass
        if fail_mode(None) == "closed":
            emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": prefixed(t("hook_error_closed", error=e)),
            }})
        print(prefixed(t("hook_error_open", error=e)), file=sys.stderr)
        sys.exit(1)
