"""Messages shown by the governance hooks, in English (default) or French.

Language: CLAUDE_GOV_LANG environment variable, else policy.json > hooks.language, else "en".
Rule reasons live in policy.json: `reason` (English) and an optional `reason_fr`.
"""
from __future__ import annotations

import os

C3_DIR = "_conf" + "identiel"  # never written literally: the C3 lock matches it in any tool input

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "prefix": "[Governance]",
        "network_secret": "Sending a secret over the network ({types})",
        "network_pii": "Sending personal data over the network ({types})",
        "dml_without_where": "{verb} without a WHERE clause",
        "pii_table": "Query on a table holding personal data ({table})",
        "sensitive_path_bash": "Access to a sensitive file ({path} ~ {pattern})",
        "sensitive_path": "Sensitive file ({path} ~ {pattern})",
        "media": "PDF or image read denied",
        "write_secret": "Secret hard-coded in {file} ({types})",
        "sensitive_search": "Search in a sensitive location ({path})",
        "web_domain": "Blocked domain ({host})",
        "web_url_pii": "URL containing sensitive data ({types})",
        "c3_denied": ("C3 content (" + C3_DIR + "): readable only when the trusted provider is active "
                      "(console › Settings › AI model). Nothing was read or sent."),
        "c3_unknown": ("Recursive search too wide to verify it avoids C3 locations: target a subfolder instead "
                       "of the project. Nothing was read or sent."),
        "hook_error_closed": "Hook error (fail-closed): {error}",
        "hook_error_open": "hook error (fail-open): {error}",
        "prompt_blocked": ("Prompt blocked: it contains forbidden data ({types}). Remove it (or reference it through "
                           "an environment variable or an ignored file), then send the prompt again."),
        "prompt_warn_proxy": "Personal data detected ({types}): it will be pseudonymized by the proxy before sending.",
        "prompt_error": "Prompt guard hook error: {error}",
        "session_trusted": ("Model actually used: {label}. Claude Code's \"Claude\" header does not reflect it. "
                            "C3 folders are readable: this session will be locked if they are read."),
        "session_claude": "Model in use: Claude (Anthropic). C3 folders are locked.",
        "audit_error": "audit error: {error}",
        "audit_write_error": "cannot write audit trail ({path}): {error}",
    },
    "fr": {
        "prefix": "[Gouvernance]",
        "network_secret": "Envoi réseau d'un secret ({types})",
        "network_pii": "Envoi réseau de données personnelles ({types})",
        "dml_without_where": "{verb} sans clause WHERE",
        "pii_table": "Requête sur une table contenant des données personnelles ({table})",
        "sensitive_path_bash": "Accès à un fichier sensible ({path} ~ {pattern})",
        "sensitive_path": "Fichier sensible ({path} ~ {pattern})",
        "media": "Lecture de PDF/image interdite",
        "write_secret": "Secret écrit en dur dans {file} ({types})",
        "sensitive_search": "Recherche dans un emplacement sensible ({path})",
        "web_domain": "Domaine interdit ({host})",
        "web_url_pii": "URL contenant des données sensibles ({types})",
        "c3_denied": ("Contenu C3 (" + C3_DIR + ") : lisible uniquement quand le fournisseur de confiance "
                      "est actif (console › Réglages › Modèle d'IA). Rien n'a été lu ni envoyé."),
        "c3_unknown": ("Recherche récursive trop large pour vérifier qu'elle ne traverse aucun emplacement C3 : "
                       "ciblez un sous-dossier du projet. Rien n'a été lu ni envoyé."),
        "hook_error_closed": "Erreur du hook (fail-closed) : {error}",
        "hook_error_open": "hook en erreur (fail-open) : {error}",
        "prompt_blocked": ("Prompt bloqué : il contient des données interdites ({types}). Retirez-les (ou "
                           "référencez-les via une variable d'environnement / un fichier ignoré) puis renvoyez le prompt."),
        "prompt_warn_proxy": "Données personnelles détectées ({types}) : elles seront pseudonymisées par le proxy avant envoi.",
        "prompt_error": "Erreur du hook de contrôle des prompts : {error}",
        "session_trusted": ("Modèle réellement utilisé : {label}. L'en-tête « Claude » de Claude Code n'en tient pas "
                            "compte. Dossiers C3 lisibles : cette session sera verrouillée s'ils sont lus."),
        "session_claude": "Modèle utilisé : Claude (Anthropic). Dossiers C3 verrouillés.",
        "audit_error": "audit en erreur : {error}",
        "audit_write_error": "audit impossible ({path}) : {error}",
    },
}

_lang = "en"


def set_language(policy: dict | None) -> str:
    """Pick the language once per hook run (env else policy else English)."""
    global _lang
    wanted = (os.environ.get("CLAUDE_GOV_LANG") or ((policy or {}).get("hooks", {}) or {}).get("language") or "en")
    _lang = wanted.lower()[:2] if wanted.lower()[:2] in MESSAGES else "en"
    return _lang


def language() -> str:
    return _lang


def t(key: str, **kw) -> str:
    text = MESSAGES[_lang].get(key) or MESSAGES["en"][key]
    return text.format(**kw) if kw else text


def prefixed(text: str) -> str:
    return f"{t('prefix')} {text}"


def rule_reason(rule: dict) -> str:
    """Reason of a policy rule in the current language (`reason_fr`…), falling back to `reason`."""
    return rule.get(f"reason_{_lang}") or rule.get("reason", "")


def policy_text(cfg: dict, key: str, default: str) -> str:
    """Localized free-text policy field, e.g. read_media_reason / read_media_reason_fr."""
    return cfg.get(f"{key}_{_lang}") or cfg.get(key) or default
