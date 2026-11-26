"""
Réglages de gouvernance modifiables dans la console (écrits dans overrides.json, relus à chaud par le
proxy et les hooks via pii.apply_overrides).

Ne sont volontairement PAS réglables ici : masquage des secrets, fichiers sensibles, verrou C3,
commandes interdites, mode fail-closed (policy.json uniquement).

Les valeurs par défaut viennent de policy.json (monté en lecture seule dans la console). Chaque
modification est historisée dans settings-history.jsonl (affichée dans le tableau de bord).
"""
from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MASKABLE_TYPES = ("EMAIL", "PHONE_FR", "IBAN", "CREDIT_CARD", "NIR", "SIRET", "IPV4")  # = pii.MASKABLE_TYPES
DECISION_KEYS = ("bash_network_pii_decision", "pii_tables_decision", "write_secret_decision")  # = pii.DECISION_KEYS

TYPE_LABELS = {
    "EMAIL": ("Adresses e-mail", "prenom.nom@domaine, contacts des documents et du code"),
    "PHONE_FR": ("Numéros de téléphone", "fixes et mobiles français, avec ou sans +33"),
    "IBAN": ("IBAN", "FR76 3000 …"),
    "CREDIT_CARD": ("Cartes bancaires", "numéros validés par la clé de Luhn"),
    "NIR": ("Numéros de sécurité sociale", "NIR, avec clé de contrôle"),
    "SIRET": ("SIRET", "identifiant d'établissement (14 chiffres)"),
    "IPV4": ("Adresses IP", "192.168.1.10 — faux positifs possibles sur les numéros de version"),
}
DECISION_LABELS = {
    "bash_network_pii_decision": ("Envoi réseau de données personnelles",
                                  "Commande curl, wget… contenant un e-mail, un nom, un IBAN… (les secrets sont toujours refusés)."),
    "pii_tables_decision": ("Requête SQL sur une table de données personnelles",
                            "SELECT, UPDATE… sur une table de la liste ci-dessous."),
    "write_secret_decision": ("Secret écrit en dur dans un fichier",
                              "Clé d'API ou mot de passe écrit dans le code par Claude."),
}
BOOL_LABELS = {
    "mask_amounts": ("Masquer les prix et montants",
                     "125 000 € HT, TJM 650… sont remplacés par des jetons. Désactiver le temps d'une tâche "
                     "qui doit calculer des totaux ou vérifier un BPU/DQE."),
    "allow_images": ("Autoriser les images",
                     "Captures d'écran et schémas envoyés au modèle tels quels (non pseudonymisables)."),
    "ner_documents": ("Noms de personnes dans les documents",
                      "Noms et lieux masqués dans les PDF convertis (CV, organigrammes) et les fichiers .md/.txt."),
    "ner_tool_results": ("Noms de personnes dans les sorties d'outils",
                         "Applique aussi la détection au code et aux résultats de commandes. Plus sûr, mais des noms "
                         "de classes ou de variables peuvent être pris pour des personnes."),
}
# Réglages historiques (avant cette version) : stockés à plat dans overrides.json
BOOL_KEYS = tuple(BOOL_LABELS)
LIST_LIMIT = 200
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
HISTORY_FILE = "settings-history.jsonl"

FALLBACK_POLICY: dict = {  # si policy.json n'est pas monté (tests, développement)
    "pii": {"patterns": [{"type": t, "enabled": t != "IPV4"} for t in MASKABLE_TYPES] + [{"type": "MONTANT"}],
            "presidio": {"score_threshold": 0.75, "scopes": ["user_text", "document"]},
            "request": {"blocked_media": ["pdf", "image"]}, "allowlist": []},
    "tool_guard": {"bash_network_pii_decision": "ask", "pii_tables_decision": "ask", "write_secret_decision": "ask",
                   "pii_tables": [], "web_deny_domains": []},
}


def _err(msg: str) -> Exception:
    from .registry import AdminError
    return AdminError(msg)


def _clean_list(values, check, label: str, lower: bool = False) -> list[str]:
    if not isinstance(values, list):
        raise _err(f"{label} : liste attendue")
    out: list[str] = []
    for v in values:
        v = " ".join(str(v).split())
        if lower:
            v = v.lower()
        if not v:
            continue
        if not check(v):
            raise _err(f"{label} : valeur invalide « {v[:60]} »")
        if v.lower() not in {x.lower() for x in out}:
            out.append(v)
    if len(out) > LIST_LIMIT:
        raise _err(f"{label} : {LIST_LIMIT} entrées au plus")
    return out


class SettingsMixin:
    """Méthodes « réglages » du Registry (config_dir, overrides_path, load sont fournis par Registry)."""

    policy_path: Optional[Path]
    config_dir: Path
    overrides_path: Path

    # ------------------------------------------------------------------ valeurs
    def base_policy(self) -> dict:
        if self.policy_path:
            try:
                return json.loads(Path(self.policy_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return FALLBACK_POLICY

    def default_settings(self) -> dict:
        pol = self.base_policy()
        pii, tg = pol.get("pii", {}), pol.get("tool_guard", {})
        pres = pii.get("presidio", {})
        enabled = {}
        for pat in pii.get("patterns", []):
            t = pat.get("type")
            if t in MASKABLE_TYPES:
                enabled[t] = enabled.get(t, False) or pat.get("enabled", True) is not False
        scopes = pres.get("scopes", ["user_text"])
        return {
            "mask_amounts": any(p.get("type") == "MONTANT" and p.get("enabled", True) is not False
                                for p in pii.get("patterns", [])),
            "allow_images": "image" not in pii.get("request", {}).get("blocked_media", ["pdf", "image"]),
            "ner_documents": "document" in scopes,
            "ner_tool_results": "tool_result" in scopes,
            "ner_threshold": float(pres.get("score_threshold", 0.75)),
            "mask_types": {t: enabled.get(t, False) for t in MASKABLE_TYPES},
            "allowlist_extra": [],
            "decisions": {k: tg.get(k, "ask") if tg.get(k) in ("ask", "deny") else "ask" for k in DECISION_KEYS},
            "pii_tables": list(tg.get("pii_tables", [])),
            "web_deny_domains_extra": [],
        }

    def _overrides(self) -> dict:
        try:
            return json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def get_settings(self) -> dict:
        d, ov = self.default_settings(), self._overrides()
        out = dict(d)
        for k in BOOL_KEYS:
            if isinstance(ov.get(k), bool):
                out[k] = ov[k]
        if isinstance(ov.get("ner_threshold"), (int, float)) and not isinstance(ov["ner_threshold"], bool):
            out["ner_threshold"] = float(ov["ner_threshold"])
        if isinstance(ov.get("mask_types"), dict):
            out["mask_types"] = {t: bool(ov["mask_types"].get(t, d["mask_types"][t])) for t in MASKABLE_TYPES}
        if isinstance(ov.get("decisions"), dict):
            out["decisions"] = {k: ov["decisions"].get(k) if ov["decisions"].get(k) in ("ask", "deny")
                                else d["decisions"][k] for k in DECISION_KEYS}
        for k in ("allowlist_extra", "pii_tables", "web_deny_domains_extra"):
            if isinstance(ov.get(k), list):
                out[k] = [str(x) for x in ov[k]]
        return out

    def locked_lists(self) -> dict:
        """Entrées de policy.json toujours actives (affichées, non supprimables depuis la console)."""
        pol = self.base_policy()
        return {"allowlist": list(pol.get("pii", {}).get("allowlist", [])),
                "web_deny_domains": list(pol.get("tool_guard", {}).get("web_deny_domains", []))}

    # ------------------------------------------------------------------ validation
    def _dictionary_terms(self) -> set[str]:
        out: set[str] = set()
        data = self.load()  # type: ignore[attr-defined]
        for c in data.get("clients", {}).values():
            out |= {c.get("name", "").lower(), *(v.lower() for v in c.get("variants", []))}
            out |= {cons.get("title", "").lower() for cons in c.get("consultations", {}).values()}
        for values in data.get("extra_terms", {}).values():
            out |= {str(v).lower() for v in values}
        out |= {p.get("name", "").lower() for p in data.get("projects", {}).values() if p.get("mask_name")}
        out.discard("")
        return out

    def _validate(self, key: str, value: Any, current: dict) -> Any:
        if key in BOOL_KEYS:
            if not isinstance(value, bool):
                raise _err(f"{key} : vrai ou faux attendu")
            return value
        if key == "ner_threshold":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.3 <= value <= 0.99:
                raise _err("Seuil de détection : valeur entre 0,30 et 0,99")
            return round(float(value), 2)
        if key == "mask_types":
            if not isinstance(value, dict) or any(k not in MASKABLE_TYPES or not isinstance(v, bool)
                                                   for k, v in value.items()):
                raise _err("Types masqués invalides")
            return {**current["mask_types"], **value}
        if key == "decisions":
            if not isinstance(value, dict) or any(k not in DECISION_KEYS or v not in ("ask", "deny")
                                                   for k, v in value.items()):
                raise _err("Décisions invalides : « ask » ou « deny »")
            return {**current["decisions"], **value}
        if key == "allowlist_extra":
            items = _clean_list(value, lambda v: 2 <= len(v) <= 100, "Exceptions")
            terms = self._dictionary_terms()
            clash = [v for v in items if v.lower() in terms]
            if clash:
                raise _err(f"« {clash[0]} » est dans le dictionnaire (client ou projet) : une exception l'enverrait "
                           "en clair. Retirez-le d'abord du dictionnaire si c'est voulu.")
            return items
        if key == "pii_tables":
            return _clean_list(value, _TABLE_RE.fullmatch, "Tables")
        if key == "web_deny_domains_extra":
            return _clean_list(value, _HOST_RE.fullmatch, "Domaines", lower=True)
        raise _err(f"Réglage inconnu : {key}")

    # ------------------------------------------------------------------ modification
    def set_settings(self, values: dict, action: str = "update") -> dict:
        from .registry import _now, atomic_write_json
        if not isinstance(values, dict):
            raise _err("Réglages invalides")
        before = self.get_settings()
        after = dict(before)
        for k, v in values.items():
            after[k] = self._validate(k, v, before)
        changes = _diff(before, after)
        if changes:
            ov = self._overrides()
            for k in values:
                ov[k] = after[k]
            atomic_write_json(self.overrides_path, ov)
            self._history({"ts": _now(), "action": action, "changes": changes,
                           "reduces": any(c["reduces"] for c in changes)})
        return after

    def reset_settings(self) -> dict:
        """Revient aux valeurs de policy.json (le fournisseur de modèle n'est pas concerné)."""
        from .registry import _now, atomic_write_json
        before = self.get_settings()
        managed = set(BOOL_KEYS) | {"ner_threshold", "mask_types", "allowlist_extra", "decisions", "pii_tables",
                                    "web_deny_domains_extra"}
        ov = {k: v for k, v in self._overrides().items() if k not in managed}
        atomic_write_json(self.overrides_path, ov)
        after = self.get_settings()
        changes = _diff(before, after)
        if changes:
            self._history({"ts": _now(), "action": "reset", "changes": changes,
                           "reduces": any(c["reduces"] for c in changes)})
        return after

    # ------------------------------------------------------------------ historique
    @property
    def history_path(self) -> Path:
        return self.config_dir / HISTORY_FILE

    def _history(self, record: dict) -> None:
        import os
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.history_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def settings_history(self, limit: int = 50) -> list[dict]:
        try:
            with open(self.history_path, encoding="utf-8") as f:
                lines = list(deque(f, maxlen=limit))
        except FileNotFoundError:
            return []
        out = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def _reduces(key: str, sub: Optional[str], old: Any, new: Any) -> bool:
    """La modification affaiblit-elle la protection ?"""
    if key in ("mask_amounts", "ner_documents", "ner_tool_results", "mask_types"):
        return old is True and new is False
    if key == "allow_images":
        return new is True and old is False
    if key == "ner_threshold":
        return new > old  # seuil plus haut : moins de noms détectés
    if key == "decisions":
        return old == "deny" and new == "ask"
    if key in ("allowlist_extra",):
        return bool(set(new) - set(old))
    if key in ("pii_tables", "web_deny_domains_extra"):
        return bool(set(old) - set(new))
    return False


def _diff(before: dict, after: dict) -> list[dict]:
    out = []
    for k in after:
        old, new = before.get(k), after[k]
        if old == new:
            continue
        if isinstance(new, dict):
            for sub in new:
                if (old or {}).get(sub) != new[sub]:
                    o = (old or {}).get(sub)
                    out.append({"key": k, "sub": sub, "old": o, "new": new[sub], "reduces": _reduces(k, sub, o, new[sub])})
        else:
            out.append({"key": k, "sub": None, "old": old, "new": new, "reduces": _reduces(k, None, old, new)})
    return out
