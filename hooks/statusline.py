#!/usr/bin/env python3
"""Ligne d'état de Claude Code : fournisseur réellement utilisé (l'en-tête de Claude Code ne le sait pas)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CLAUDE_GOV_CONFIG_DIR") or Path.home() / ".config" / "claude-governance")


def read(name: str) -> dict:
    try:
        return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> None:
    try:
        session = json.loads(sys.stdin.read() or "{}").get("session_id", "")
    except ValueError:
        session = ""
    provider = read("overrides.json").get("provider", "claude")
    c3 = session in read("c3-sessions.json")
    if provider == "trusted":
        label = read("overrides.json").get("provider_label") or "Fournisseur de confiance"
        line = f"\033[35m🛡 {label}\033[0m · C3 lisible"
    else:
        line = "\033[34m🛡 Claude · Anthropic\033[0m · C3 verrouillé"
    if c3:
        line += " · \033[31msession C3 : jamais envoyée à Anthropic\033[0m"
    print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # la ligne d'état ne doit jamais gêner
        print("🛡 Gouvernance")
