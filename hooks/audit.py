#!/usr/bin/env python3
"""
Hook d'audit générique (PostToolUse, PostToolUseFailure, SessionStart, SessionEnd,
ConfigChange, PermissionDenied, SubagentStart, Stop...).

N'interfère jamais : sort toujours en code 0, même en cas d'erreur.
Ne journalise ni le contenu des fichiers ni les sorties d'outils.
"""
from __future__ import annotations

import sys

from common import audit, emit, end_c3_session, load_policy, provider, provider_label, read_input

KEEP = ("session_id", "cwd", "permission_mode", "tool_name", "source", "reason",
        "agent_type", "file_path", "trigger", "model", "error_type")


def main() -> None:
    policy = load_policy()
    data = read_input()
    event = data.get("hook_event_name", "unknown")
    rec = {"event": event}
    for k in KEEP:
        if data.get(k) is not None:
            rec[k] = data[k]
    if event in ("PostToolUse", "PostToolUseFailure"):
        from guard_tool import summarize
        rec["target"] = summarize(data.get("tool_name", ""), data.get("tool_input") or {}, policy)
        rec["outcome"] = "success" if event == "PostToolUse" else "failure"
    if event == "SessionEnd":
        end_c3_session(data.get("session_id", ""))
    if event == "ConfigChange":
        rec["decision"] = "config_changed"
    audit(policy, rec)
    if event == "SessionStart":
        # L'en-tête de Claude Code affiche le compte Claude même quand le proxy redirige ailleurs.
        if provider() == "trusted":
            emit({"systemMessage": f"[Gouvernance] Modèle réellement utilisé : {provider_label()}. "
                                   "L'en-tête « Claude » de Claude Code n'en tient pas compte. "
                                   "Dossiers C3 lisibles : cette session sera verrouillée s'ils sont lus."})
        else:
            emit({"systemMessage": "[Gouvernance] Modèle utilisé : Claude (Anthropic). Dossiers C3 verrouillés."})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # l'audit ne doit jamais bloquer Claude Code
        print(f"[Gouvernance] audit en erreur : {e}", file=sys.stderr)
    sys.exit(0)
