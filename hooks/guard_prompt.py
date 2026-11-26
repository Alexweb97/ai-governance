#!/usr/bin/env python3
"""
Hook UserPromptSubmit : contrôle le prompt avant qu'il parte vers le modèle.

- types listés dans prompt_guard.block_types (secrets, NIR, CB...) -> prompt bloqué ;
- autres PII -> avertissement à l'utilisateur (le proxy les pseudonymisera) ;
- dans tous les cas : trace d'audit (types détectés, empreinte, jamais le texte en clair).
"""
from __future__ import annotations

import sys
from collections import Counter
from fnmatch import fnmatch

from common import audit, detector, emit, fail_mode, load_policy, read_input, sha


def main() -> None:
    policy = load_policy()
    data = read_input()
    prompt = data.get("prompt", "") or ""
    cfg = policy.get("prompt_guard", {})
    det = detector(policy)

    types = Counter(s.type for s in det.detect(prompt))
    blocked = sorted(t for t in types if any(fnmatch(t, p) for p in cfg.get("block_types", [])))
    warned = sorted(t for t in types if t not in blocked
                    and any(fnmatch(t, p) for p in cfg.get("warn_types", [])))

    record = {
        "event": "UserPromptSubmit",
        "session_id": data.get("session_id"),
        "cwd": data.get("cwd"),
        "prompt_sha": sha(prompt),
        "prompt_chars": len(prompt),
        "detected": dict(types),
    }
    if policy.get("audit", {}).get("log_prompt_text"):
        from common import redact
        record["prompt_redacted"] = redact(prompt, det)

    if blocked:
        audit(policy, {**record, "decision": "block", "rule": "prompt_guard.block_types",
                       "reason": ",".join(blocked)})
        emit({
            "decision": "block",
            "reason": (
                "[Gouvernance] Prompt bloqué : il contient des données interdites "
                f"({', '.join(blocked)}). Retirez-les (ou référencez-les via une variable "
                "d'environnement / un fichier ignoré) puis renvoyez le prompt."
            ),
        })

    audit(policy, {**record, "decision": "warn" if warned else "allow"})
    if warned:
        emit({
            "systemMessage": (
                f"[Gouvernance] Données personnelles détectées ({', '.join(warned)}) : "
                "elles seront pseudonymisées par le proxy avant envoi."
            )
        })
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # pragma: no cover
        if fail_mode(None) == "closed":
            print(f"[Gouvernance] Erreur du hook de contrôle des prompts : {e}", file=sys.stderr)
            sys.exit(2)  # code 2 = bloquant pour UserPromptSubmit
        print(f"[Gouvernance] hook en erreur (fail-open) : {e}", file=sys.stderr)
        sys.exit(1)
