"""
Proxy de gouvernance entre Claude Code et l'API Anthropic.

  Claude Code --(ANTHROPIC_BASE_URL=http://127.0.0.1:8787)--> proxy --> https://api.anthropic.com

  1. POST /v1/messages et /v1/messages/count_tokens : pseudonymisation de la requête
     (regex + validateurs + Presidio), journalisation des détections (types, jamais les valeurs).
  2. Réponse : ré-identification (JSON ou flux SSE) pour que Claude Code écrive les
     vraies valeurs dans vos fichiers.
  3. Toutes les autres routes : relais transparent.

Fail-closed : si la détection NER est requise et indisponible, la requête est refusée (503).

Fournisseur de modèle (interrupteur de la console, overrides.json "provider") :
  - "claude" : https://api.anthropic.com (abonnement de l'utilisateur, en-têtes relayés tels quels) ;
  - "trusted" : fournisseur de confiance (TRUSTED_URL), au format Anthropic Messages : LLM auto-hébergé,
    ou passerelle LiteLLM vers OpenAI, Gemini, Mistral, Ollama... Le jeton Claude n'est jamais transmis :
    il est remplacé par TRUSTED_API_KEY, et le modèle demandé par TRUSTED_MODEL. Seul ce fournisseur
    peut lire le contenu C3.
La pseudonymisation s'applique dans les deux cas : une session peut changer de fournisseur sans
qu'aucune donnée en clair n'atteigne Anthropic.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .pii import (Detector, KnownValues, Pseudonymizer, RehydrationPolicy, RequestOptions, apply_overrides,
                  load_json, load_terms, pseudonymize_request, rehydrate_response, with_terms)
from .presidio_client import PresidioNER, PresidioUnavailable
from .store import build_store
from .stream import SSEProcessor

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("governance.proxy")

# ---------------------------------------------------------------- configuration
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "https://api.anthropic.com").rstrip("/")
POLICY_PATH = os.environ.get("POLICY_PATH", "/etc/claude-governance/policy.json")
CONFIG_DIR = os.environ.get("GOV_CONFIG_DIR", "/var/lib/claude-governance")  # écrit par la console
TERMS_PATH = os.environ.get("TERMS_PATH", f"{CONFIG_DIR}/terms.json")
OVERRIDES_PATH = os.environ.get("OVERRIDES_PATH", f"{CONFIG_DIR}/overrides.json")
C3_SESSIONS_PATH = os.environ.get("C3_SESSIONS_PATH", f"{CONFIG_DIR}/c3-sessions.json")
C3_PATHS_PATH = os.environ.get("C3_PATHS_PATH", f"{CONFIG_DIR}/c3-paths.json")  # écran Projets de la console
PRESIDIO_URL = os.environ.get("PRESIDIO_URL", "http://presidio:3000")
REDIS_URL = os.environ.get("REDIS_URL")
AUDIT_LOG = os.environ.get("AUDIT_LOG", "/var/log/claude-governance/proxy-audit.jsonl")
TRUSTED_URL = os.environ.get("TRUSTED_URL", "").rstrip("/")
TRUSTED_API_KEY = os.environ.get("TRUSTED_API_KEY", "")
TRUSTED_MODEL = os.environ.get("TRUSTED_MODEL", "")
TRUSTED_NAME = os.environ.get("TRUSTED_NAME", "") or "Fournisseur de confiance"
TRUSTED_AUTH = os.environ.get("TRUSTED_AUTH", "x-api-key").lower()  # "x-api-key" ou "bearer"
PROVIDERS = ("claude", "trusted")
SECRET = os.environ.get("PSEUDO_SECRET", "")
if len(SECRET) < 32:
    raise SystemExit("PSEUDO_SECRET manquant ou trop court (>= 32 caractères). Voir .env")

BASE_POLICY = json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))
BASE_PRES = BASE_POLICY["pii"].get("presidio", {})

# Le service Presidio est construit une fois ; ses scopes (où appliquer le NER) sont rechargeables.
NER = None
if BASE_PRES.get("enabled", False):
    NER = PresidioNER(
        url=PRESIDIO_URL,
        language=BASE_PRES.get("language", "fr"),
        entities=BASE_PRES.get("entities", ["PERSON", "LOCATION"]),
        score_threshold=float(BASE_PRES.get("score_threshold", 0.75)),
        max_chars=int(BASE_PRES.get("max_chars", 20000)),
        required=bool(BASE_PRES.get("required", True)),
    )

STORE = build_store(REDIS_URL, int(BASE_POLICY["pii"].get("mapping_ttl_seconds", 86400)))
KNOWN = KnownValues()  # partagé entre rechargements de configuration


@dataclass(frozen=True)
class Runtime:
    pseudo: Pseudonymizer
    rehydration: RehydrationPolicy
    request_opts: RequestOptions
    ner_scopes: frozenset
    presidio_required: bool
    terms_count: int
    provider: str
    c3_marker: Optional[re.Pattern]
    c3_paths: Optional[re.Pattern]  # chemins absolus déclarés C3 (et leur contenu)


def build_runtime() -> Runtime:
    overrides = load_json(OVERRIDES_PATH, {})
    policy = apply_overrides(json.loads(Path(POLICY_PATH).read_text(encoding="utf-8")), overrides)
    provider = overrides.get("provider", "claude")
    terms = load_terms(TERMS_PATH)
    pii_cfg = with_terms(policy["pii"], terms)
    pres = pii_cfg.get("presidio", {})
    if NER is not None:  # seuil réglable dans la console, appliqué au service existant
        NER.score_threshold = float(pres.get("score_threshold", NER.score_threshold))
    return Runtime(
        pseudo=Pseudonymizer(Detector(pii_cfg, ner=NER), SECRET.encode(), STORE, known=KNOWN),
        rehydration=RehydrationPolicy(pii_cfg.get("rehydration")),
        request_opts=RequestOptions.from_policy(pii_cfg.get("request")),
        ner_scopes=frozenset(pres.get("scopes", ["user_text"])),
        presidio_required=bool(pres.get("required", True)),
        terms_count=sum(len(v) for k, v in terms.items() if isinstance(v, list) and not k.startswith("_")),
        provider=provider if provider in PROVIDERS else "claude",
        c3_marker=re.compile(policy["tool_guard"]["c3_marker_regex"])
        if policy.get("tool_guard", {}).get("c3_marker_regex") else None,
        c3_paths=_c3_paths_regex(load_json(C3_PATHS_PATH, {}).get("paths", [])),
    )


def _c3_paths_regex(paths: list) -> Optional[re.Pattern]:
    """Un chemin déclaré, suivi d'une fin de chemin ou d'un descendant (pas /a/config-bis pour /a/config)."""
    paths = sorted({p.rstrip("/") for p in paths if isinstance(p, str) and p.startswith("/")}, key=len, reverse=True)
    if not paths:
        return None
    return re.compile("(?:" + "|".join(re.escape(p) for p in paths) + r")(?![\w.-])")


class RuntimeHolder:
    """Recharge la politique, le dictionnaire et les réglages de la console quand ils changent."""

    CHECK_EVERY = 2.0  # secondes

    def __init__(self):
        self._lock = threading.Lock()
        self._sig = self._signature()
        self._rt = build_runtime()
        self._checked = time.monotonic()

    @staticmethod
    def _signature() -> tuple:
        sig = []
        for p in (POLICY_PATH, TERMS_PATH, OVERRIDES_PATH, C3_PATHS_PATH):
            try:
                st = os.stat(p)
                sig.append((st.st_mtime_ns, st.st_size))
            except FileNotFoundError:
                sig.append(None)
        return tuple(sig)

    def get(self) -> Runtime:
        now = time.monotonic()
        if now - self._checked < self.CHECK_EVERY:
            return self._rt
        with self._lock:
            self._checked = now
            sig = self._signature()
            if sig != self._sig:
                try:
                    self._rt = build_runtime()
                    self._sig = sig
                    log.info("configuration rechargée (%d termes, fournisseur %s)",
                             self._rt.terms_count, self._rt.provider)
                    audit({"event": "config_reloaded", "terms": self._rt.terms_count,
                           "provider": self._rt.provider})
                except Exception as e:  # fichier en cours d'écriture ou invalide : on garde l'ancienne
                    ERRORS.labels("reload").inc()
                    log.error("rechargement impossible, configuration précédente conservée : %s", e)
        return self._rt


GOVERNED_PATHS = {"/v1/messages", "/v1/messages/count_tokens"}
HOP_BY_HOP = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "accept-encoding", "proxy-authorization", "proxy-connection", "te", "trailer", "upgrade",
}
RESP_DROP = HOP_BY_HOP | {"content-encoding"}

# ---------------------------------------------------------------- métriques
REQUESTS = Counter("gov_proxy_requests_total", "Requêtes relayées", ["path", "status"])
PROVIDER_REQUESTS = Counter("gov_provider_requests_total", "Requêtes de modèle par fournisseur", ["provider"])
DETECTIONS = Counter("gov_pii_detections_total", "Valeurs pseudonymisées", ["entity", "scope"])
ERRORS = Counter("gov_proxy_errors_total", "Erreurs du proxy", ["kind"])
LATENCY = Histogram("gov_proxy_latency_seconds", "Latence totale (upstream inclus)", ["path"],
                    buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160, 320))
PSEUDO_TIME = Histogram("gov_pseudonymization_seconds", "Temps de pseudonymisation",
                        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))

_audit_lock = threading.Lock()
RUNTIME: "RuntimeHolder"  # initialisé après la définition d'audit()


def audit(record: dict) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "component": "proxy", **record}
    line = json.dumps(record, ensure_ascii=False)
    try:
        Path(AUDIT_LOG).parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock, open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        log.error("audit write failed: %s", e)


RUNTIME = RuntimeHolder()


def _log_structure(rid: str, body: dict) -> None:
    """Diagnostic : où se trouve le répertoire de travail dans la requête (aucune valeur journalisée)."""
    def where(text) -> str:
        return f"len={len(text)} clients={'/clients/' in text}" if isinstance(text, str) else type(text).__name__
    sysb = body.get("system")
    items = [f"system[str] {where(sysb)}"] if isinstance(sysb, str) else \
        [f"system[{i}] {b.get('type')} {where(b.get('text'))}" for i, b in enumerate(sysb or []) if isinstance(b, dict)]
    for i, m in enumerate(body.get("messages", []) or []):
        c = m.get("content")
        if isinstance(c, str):
            items.append(f"msg[{i}] {m.get('role')} str {where(c)}")
        else:
            for j, b in enumerate(c or []):
                inner = b.get("text") or b.get("content") if isinstance(b, dict) else None
                if isinstance(inner, list):
                    inner = " ".join(x.get("text", "") for x in inner if isinstance(x, dict))
                items.append(f"msg[{i}][{j}] {m.get('role')} {b.get('type')} {where(inner)}")
    log.warning("STRUCTURE rid=%s\n  %s", rid, "\n  ".join(items))


# ---------------------------------------------------------------- verrou C3
class C3Sessions:
    """Sessions Claude Code ayant lu du contenu C3 (registre écrit par les hooks, relu à chaud).

    Fail-closed : si le registre existe mais est illisible, toutes les requêtes vers Anthropic sont
    refusées (on ne sait plus quelles sessions sont sûres)."""

    def __init__(self, path: str):
        self.path = path
        self._sig: Any = ()
        self._ids: frozenset = frozenset()
        self._error: Optional[str] = None
        self._lock = threading.Lock()

    def state(self) -> tuple[frozenset, Optional[str]]:
        try:
            st = os.stat(self.path)
            sig: Any = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return frozenset(), None
        with self._lock:
            if sig != self._sig:
                try:
                    data = json.loads(Path(self.path).read_text(encoding="utf-8"))
                    self._ids, self._error = frozenset(data), None
                except (OSError, ValueError) as e:
                    self._ids, self._error = frozenset(), f"registre des sessions C3 illisible ({e})"
                self._sig = sig
            return self._ids, self._error


C3 = C3Sessions(C3_SESSIONS_PATH)


def _executed_tool_inputs(body: dict):
    """Entrées des appels d'outils réellement exécutés : une tentative refusée par un hook
    (tool_result en erreur) n'a rien lu et ne doit pas verrouiller la session."""
    blocks = [b for m in body.get("messages", []) or [] if isinstance(m, dict) and isinstance(m.get("content"), list)
              for b in m["content"] if isinstance(b, dict)]
    ok = {b.get("tool_use_id") for b in blocks if b.get("type") == "tool_result" and not b.get("is_error")}
    for b in blocks:
        if b.get("type") in ("tool_use", "server_tool_use") and b.get("id") in ok:
            yield json.dumps(b.get("input"), ensure_ascii=False)


def c3_violation(rt: "Runtime", session_id: str, body: dict) -> Optional[str]:
    """Raison du refus si la requête (vers Anthropic) porte du contenu C3, sinon None."""
    ids, error = C3.state()
    if error:
        return error
    if session_id and session_id in ids:
        return "cette session a lu du contenu C3 avec le fournisseur de confiance"
    if rt.c3_marker is not None and any(rt.c3_marker.search(s) for s in _executed_tool_inputs(body)):
        return "l'historique contient un accès à un dossier C3"
    if rt.c3_paths is not None and any(rt.c3_paths.search(s) for s in _executed_tool_inputs(body)):
        return "l'historique contient un accès à un chemin déclaré C3"
    return None


# En-têtes propres au compte Anthropic : jamais transmis au fournisseur de confiance.
_ANTHROPIC_ONLY = {"authorization", "x-api-key", "cookie", "anthropic-beta"}


def trusted_auth() -> dict:
    """En-tête d'authentification du fournisseur de confiance (TRUSTED_AUTH : x-api-key ou bearer)."""
    bearer = TRUSTED_AUTH == "bearer"
    name = "authorization" if bearer else "x-api-key"
    return {name: f"Bearer {TRUSTED_API_KEY}" if bearer else TRUSTED_API_KEY}


def trusted_headers(headers: dict) -> dict:
    out = {k: v for k, v in headers.items() if k.lower() not in _ANTHROPIC_ONLY}
    out.update(trusted_auth())
    return out


def anthropic_error(status: int, message: str, etype: str = "api_error") -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"type": "error", "error": {"type": etype, "message": message}})


# ---------------------------------------------------------------- application
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.trusted = httpx.AsyncClient(
        base_url=TRUSTED_URL or "http://trusted.invalid",
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0),
    )
    app.state.client = httpx.AsyncClient(
        base_url=UPSTREAM_URL,
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0),
    )
    rt = RUNTIME.get()
    log.info("proxy prêt : upstream=%s presidio=%s scopes_ner=%s termes=%d", UPSTREAM_URL,
             bool(NER), sorted(rt.ner_scopes), rt.terms_count)
    yield
    await app.state.client.aclose()
    await app.state.trusted.aclose()


app = FastAPI(title="Claude Governance Proxy", lifespan=lifespan, docs_url=None, redoc_url=None)


_trusted_health: dict = {"at": 0.0, "value": None}


async def trusted_health(app_: FastAPI) -> str:
    """État du fournisseur de confiance (mis en cache 30 s) :
    ok / not_configured / key_missing / auth_error / down."""
    if not TRUSTED_URL or not TRUSTED_MODEL:
        return "not_configured"
    if not TRUSTED_API_KEY:
        return "key_missing"
    if time.monotonic() - _trusted_health["at"] < 30 and _trusted_health["value"]:
        return _trusted_health["value"]
    try:
        r = await app_.state.trusted.get("/v1/models", headers=trusted_auth(), timeout=8)
        value = "ok" if r.status_code == 200 else "auth_error" if r.status_code in (401, 403) else "down"
    except httpx.HTTPError:
        value = "down"
    _trusted_health.update(at=time.monotonic(), value=value)
    return value


@app.get("/healthz")
async def healthz(request: Request):
    status = {"proxy": "ok", "presidio": None, "redis": None}
    if NER is not None:
        status["presidio"] = "ok" if await run_in_threadpool(NER.healthy) else "down"
    if hasattr(STORE, "ping"):
        status["redis"] = "ok" if await run_in_threadpool(STORE.ping) else "down"
    status["terms"] = RUNTIME.get().terms_count
    status["provider"] = RUNTIME.get().provider
    status["trusted"] = await trusted_health(request.app) if RUNTIME.get().provider == "trusted" else None
    degraded = status["presidio"] == "down" and RUNTIME.get().presidio_required
    return JSONResponse(status_code=503 if degraded else 200, content=status)


@app.post("/_gov/preview")
async def preview(request: Request):
    """Aperçu de ce qui partirait vers l'API pour un texte (utilisé par la console).
    Ne renvoie que la version pseudonymisée et les types : jamais de correspondance jeton -> valeur."""
    try:
        payload = await request.json()
        text = str(payload.get("text", ""))[:20000]
        scope = "document" if payload.get("scope") == "document" else "user_text"
    except ValueError:
        return anthropic_error(400, "JSON invalide", "invalid_request_error")
    rt = RUNTIME.get()
    try:
        out, spans = await run_in_threadpool(rt.pseudo.pseudonymize, text, scope in rt.ner_scopes)
    except PresidioUnavailable as e:
        return anthropic_error(503, str(e))
    return {"text": out, "detections": [{"type": s.type, "source": s.source} for s in spans]}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def relay(path: str, request: Request):
    t0 = time.perf_counter()
    url_path = "/" + path
    metric_path = url_path if url_path in GOVERNED_PATHS else "other"
    rid = uuid.uuid4().hex[:12]
    raw = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers["accept-encoding"] = "identity"  # flux non compressé pour pouvoir le réécrire

    governed = request.method == "POST" and url_path in GOVERNED_PATHS
    rt = RUNTIME.get()
    if governed:
        try:
            body = json.loads(raw)
        except ValueError:
            ERRORS.labels("bad_json").inc()
            return anthropic_error(400, "Corps JSON invalide", "invalid_request_error")
        if os.environ.get("GOV_DEBUG_STRUCTURE"):
            _log_structure(rid, body)
        if rt.provider != "trusted":
            reason = c3_violation(rt, request.headers.get("x-claude-code-session-id", ""), body)
            if reason:
                ERRORS.labels("c3_blocked").inc()
                audit({"event": "c3_blocked", "request_id": rid, "reason": reason})
                # 400 et non 403 : Claude Code présente un 403 comme un échec d'authentification.
                return anthropic_error(400, f"[Gouvernance] Requête refusée : {reason}. Le contenu C3 ne "
                                            "doit jamais être envoyé à Anthropic. Rebasculez sur le fournisseur de confiance "
                                            "(console › Réglages) ou ouvrez une nouvelle session.",
                                       "invalid_request_error")
        tp = time.perf_counter()
        try:
            stats = await run_in_threadpool(pseudonymize_request, body, rt.pseudo, rt.ner_scopes, rt.request_opts)
        except PresidioUnavailable as e:
            ERRORS.labels("presidio_unavailable").inc()
            audit({"event": "request_blocked", "request_id": rid, "reason": "presidio_unavailable"})
            return anthropic_error(503, f"[Gouvernance] Détection PII indisponible, requête refusée "
                                        f"(fail-closed). {e}")
        PSEUDO_TIME.observe(time.perf_counter() - tp)
        by_type: dict[str, int] = {}
        for (etype, scope), n in stats.items():
            DETECTIONS.labels(etype, scope).inc(n)
            by_type[etype] = by_type.get(etype, 0) + n
        if by_type:
            audit({"event": "pii_pseudonymized", "request_id": rid, "path": url_path,
                   "model": TRUSTED_MODEL if rt.provider == "trusted" else body.get("model"),
                   "provider": rt.provider, "counts": by_type,
                   "total": sum(by_type.values())})
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")

    client: httpx.AsyncClient = request.app.state.client
    to_trusted = governed and rt.provider == "trusted"
    if governed:
        PROVIDER_REQUESTS.labels(rt.provider).inc()
    if to_trusted:
        missing = [k for k, v in (("TRUSTED_URL", TRUSTED_URL), ("TRUSTED_MODEL", TRUSTED_MODEL),
                                  ("TRUSTED_API_KEY", TRUSTED_API_KEY)) if not v]
        if missing:
            return anthropic_error(503, f"[Gouvernance] {TRUSTED_NAME} est sélectionné dans la console mais "
                                        f"sa configuration est incomplète : {', '.join(missing)}.")
        if url_path == "/v1/messages/count_tokens":
            # Route souvent absente hors Anthropic : estimation locale (~4 caractères par token).
            return JSONResponse({"input_tokens": max(1, len(raw) // 4)})
        client = request.app.state.trusted
        headers = trusted_headers(headers)
        body = json.loads(raw)
        body["model"] = TRUSTED_MODEL
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    upstream_req = client.build_request(request.method, url_path, params=request.url.query or None,
                                        headers=headers, content=raw)
    try:
        upstream = await client.send(upstream_req, stream=True)
    except httpx.HTTPError as e:
        ERRORS.labels("upstream").inc()
        REQUESTS.labels(metric_path, "502").inc()
        name = TRUSTED_NAME if to_trusted else "API Anthropic"
        return anthropic_error(502, f"[Gouvernance] {name} injoignable : {e}")

    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in RESP_DROP}
    ctype = upstream.headers.get("content-type", "")
    REQUESTS.labels(metric_path, str(upstream.status_code)).inc()

    if "text/event-stream" in ctype:
        processor = SSEProcessor(rt.pseudo, rt.rehydration, strict=to_trusted) if governed else None

        async def gen():
            try:
                async for chunk in upstream.aiter_bytes():
                    out = processor.feed(chunk) if processor else chunk
                    if out:
                        yield out
                if processor:
                    tail = processor.close()
                    if tail:
                        yield tail
            except Exception as e:  # coupure réseau, erreur de décodage...
                ERRORS.labels("stream").inc()
                log.exception("stream error rid=%s: %s", rid, e)
                raise
            finally:
                await upstream.aclose()
                LATENCY.labels(metric_path).observe(time.perf_counter() - t0)

        return StreamingResponse(gen(), status_code=upstream.status_code, headers=resp_headers)

    content = await upstream.aread()
    await upstream.aclose()
    if governed and url_path == "/v1/messages" and upstream.status_code == 200 \
            and "application/json" in ctype:
        try:
            data = json.loads(content)
            rehydrate_response(data, rt.pseudo, rt.rehydration)
            content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except ValueError:
            ERRORS.labels("rehydrate").inc()
    LATENCY.labels(metric_path).observe(time.perf_counter() - t0)
    return Response(content=content, status_code=upstream.status_code, headers=resp_headers)
