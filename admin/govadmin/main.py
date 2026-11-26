"""
API de la console d'administration (clients, consultations, réglages, état) + application React.

http://localhost:8788 (lié à 127.0.0.1). Authentification : POST /api/session avec ADMIN_PASSWORD,
puis cookie de session signé (HttpOnly, SameSite=Strict). Les requêtes de modification exigent en
plus l'en-tête X-Gov-Admin, qu'un site tiers ne peut pas ajouter sans pré-vol CORS (refusé).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .registry import DESTINATIONS, PROVIDERS, AdminError, Registry
from .settings import BOOL_LABELS, DECISION_LABELS, TYPE_LABELS

HERE = Path(__file__).resolve().parent
WEBAPP_DIR = Path(os.environ.get("WEBAPP_DIR", HERE / "webapp"))  # build Vite (npm run build)
CONFIG_DIR = Path(os.environ.get("GOV_CONFIG_DIR", "/var/lib/claude-governance"))
CLIENTS_DIR = Path(os.environ.get("CLIENTS_DIR", "/data/clients"))
HOST_CLIENTS_DIR = os.environ.get("HOST_CLIENTS_DIR", "~/clients")
# Projets de code : dossier monté en lecture seule, et son chemin sur l'hôte (utilisé par les hooks)
PROJECTS_DIR = Path(os.environ.get("PROJECTS_DIR", "/data/projects"))
HOST_PROJECTS_DIR = os.environ.get("HOST_PROJECTS_DIR", str(PROJECTS_DIR))
# policy.json (lecture seule) : valeurs par défaut des réglages
POLICY_PATH = Path(os.environ.get("POLICY_PATH", "/etc/claude-governance/policy.json"))
LOG_DIR = Path(os.environ.get("GOV_LOG_DIR", "/var/log/claude-governance"))
PROXY_URL = os.environ.get("PROXY_URL", "http://proxy:8787").rstrip("/")
GRAFANA_URL = os.environ.get("GRAFANA_PUBLIC_URL", "http://localhost:3001")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if len(ADMIN_PASSWORD) < 12:
    raise SystemExit("ADMIN_PASSWORD manquant ou trop court (>= 12 caractères). Voir .env")

SESSION_COOKIE = "gov_session"
SESSION_TTL = 12 * 3600
# Clé de signature propre à ce démarrage : un redémarrage de la console déconnecte.
_SESSION_KEY = hashlib.sha256(secrets.token_bytes(32) + ADMIN_PASSWORD.encode()).digest()

REG = Registry(CONFIG_DIR, CLIENTS_DIR, PROJECTS_DIR, HOST_PROJECTS_DIR, POLICY_PATH)


# ------------------------------------------------------------------ session
def _sign(payload: str) -> str:
    return hmac.new(_SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()


def make_session() -> str:
    payload = f"{int(time.time()) + SESSION_TTL}.{secrets.token_hex(8)}"
    return base64.urlsafe_b64encode(f"{payload}.{_sign(payload)}".encode()).decode()


def valid_session(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(".", 1)
        expiry = int(payload.split(".", 1)[0])
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(sig, _sign(payload)) and expiry > time.time()


def auth(request: Request) -> None:
    if not valid_session(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(401, "Session expirée : reconnectez-vous")


def mutation(request: Request, _=Depends(auth)) -> None:
    """Protection CSRF des requêtes de modification (en plus du cookie SameSite=Strict)."""
    if request.headers.get("x-gov-admin") != "1":
        raise HTTPException(403, "Requête refusée (en-tête de la console manquant)")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Requête refusée (origine différente)")


app = FastAPI(title="Console de gouvernance", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(AdminError)
async def admin_error(_request: Request, exc: AdminError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail}, headers=exc.headers)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; font-src 'self'; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ session
@app.get("/api/session")
async def session_status(request: Request):
    return {"authenticated": valid_session(request.cookies.get(SESSION_COOKIE))}


@app.post("/api/session")
async def login(payload: dict, request: Request, response: Response):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Origine différente")
    pwd = str(payload.get("password", ""))
    if not secrets.compare_digest(pwd.encode(), ADMIN_PASSWORD.encode()):
        await asyncio.sleep(1.0)  # freine les essais en série
        raise HTTPException(401, "Mot de passe incorrect")
    response.set_cookie(SESSION_COOKIE, make_session(), max_age=SESSION_TTL, httponly=True,
                        samesite="strict", path="/")
    return {"authenticated": True}


@app.delete("/api/session")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


# ------------------------------------------------------------------ lecture
@app.get("/api/clients", dependencies=[Depends(auth)])
async def api_clients():
    return {"clients": REG.list_clients(), "next_code": REG.next_code()}


@app.get("/api/clients/{code}", dependencies=[Depends(auth)])
async def api_client(code: str):
    try:
        return REG.get_client(code)
    except AdminError:
        raise HTTPException(404, "Client introuvable") from None


@app.get("/api/clients/{code}/{ref}", dependencies=[Depends(auth)])
async def api_consultation(code: str, ref: str):
    try:
        client = REG.get_client(code)
        REG.ensure_structure(code, ref)
        files = REG.list_files(code, ref)
    except AdminError:
        raise HTTPException(404, "Consultation introuvable") from None
    cons = next((c for c in client["consultations"] if c["ref"] == ref), {"ref": ref, "title": ""})
    return {
        "client": {"code": client["code"], "name": client.get("name", ""), "declared": client["declared"]},
        "consultation": cons,
        "files": files,
        "command": f"cd {HOST_CLIENTS_DIR}/{code}/{ref}/travail && claude",
        "destinations": DESTINATIONS,
    }


@app.get("/api/settings", dependencies=[Depends(auth)])
async def api_get_settings():
    lab = lambda d: {k: {"title": t, "help": h} for k, (t, h) in d.items()}  # noqa: E731
    return {"settings": REG.get_settings(), "defaults": REG.default_settings(), "locked": REG.locked_lists(),
            "labels": lab(BOOL_LABELS), "type_labels": lab(TYPE_LABELS), "decision_labels": lab(DECISION_LABELS),
            "history": REG.settings_history(20), "policy_loaded": POLICY_PATH.is_file()}


@app.get("/api/status", dependencies=[Depends(auth)])
async def api_status():
    health: dict = {}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{PROXY_URL}/healthz")
            health = r.json()
            health["ok"] = r.status_code == 200
    except Exception as e:
        health = {"ok": False, "error": str(e)}
    clients = REG.list_clients()
    return {
        "health": health,
        "clients": {"declared": sum(1 for c in clients if c["declared"]),
                    "undeclared": [c["code"] for c in clients if not c["declared"]],
                    "consultations": sum(len(c["consultations"]) for c in clients)},
        "events": recent_events(),
        "provider": {"selected": REG.get_provider(), "active": health.get("provider"),
                     **PROVIDERS[REG.get_provider()]},
        "grafana_url": GRAFANA_URL,
    }


# ------------------------------------------------------------------ modifications
@app.post("/api/clients", dependencies=[Depends(mutation)])
async def api_create_client(payload: dict):
    code = REG.save_client(payload.get("code", ""), payload.get("name", ""),
                           payload.get("variants", ""), create=True)
    return {"ok": True, "code": code}


@app.put("/api/clients/{code}", dependencies=[Depends(mutation)])
async def api_update_client(code: str, payload: dict):
    REG.save_client(code, payload.get("name", ""), payload.get("variants", ""), create=False)
    return {"ok": True}


@app.delete("/api/clients/{code}", dependencies=[Depends(mutation)])
async def api_delete_client(code: str):
    REG.delete_client(code)
    return {"ok": True}


@app.post("/api/clients/{code}/consultations", dependencies=[Depends(mutation)])
async def api_create_consultation(code: str, payload: dict):
    ref = REG.add_consultation(code, payload.get("ref", ""), payload.get("title", ""))
    return {"ok": True, "ref": ref}


@app.put("/api/clients/{code}/{ref}", dependencies=[Depends(mutation)])
async def api_update_consultation(code: str, ref: str, payload: dict):
    REG.update_consultation(code, ref, payload.get("title", ""))
    return {"ok": True}


@app.post("/api/clients/{code}/{ref}/files", dependencies=[Depends(mutation)])
async def api_upload(code: str, ref: str, dest: str = Form(...), files: list[UploadFile] = File(...)):
    saved = [REG.save_upload(code, ref, dest, f.filename or "", f.file) for f in files]
    return {"ok": True, "saved": saved}


@app.post("/api/clients/{code}/{ref}/files/move", dependencies=[Depends(mutation)])
async def api_move(code: str, ref: str, payload: dict):
    return {"ok": True, "path": REG.move_file(code, ref, payload.get("path", ""), payload.get("dest", ""))}


@app.post("/api/clients/{code}/{ref}/files/delete", dependencies=[Depends(mutation)])
async def api_delete_file(code: str, ref: str, payload: dict):
    REG.delete_file(code, ref, payload.get("path", ""))
    return {"ok": True}


# ------------------------------------------------------------------ projets de code
def _project_detail(pid: str) -> dict:
    p = REG.get_project(pid)
    return {**p, "command": f"cd {p['host_path']} && claude"}


@app.get("/api/projects", dependencies=[Depends(auth)])
async def api_projects():
    return {"projects": REG.list_projects(), "root": HOST_PROJECTS_DIR,
            "mounted": PROJECTS_DIR.is_dir()}


@app.get("/api/projects/candidates", dependencies=[Depends(auth)])
async def api_project_candidates():
    return {"candidates": REG.project_candidates(), "root": HOST_PROJECTS_DIR}


@app.get("/api/projects/{pid}", dependencies=[Depends(auth)])
async def api_project(pid: str):
    try:
        return _project_detail(pid)
    except AdminError:
        raise HTTPException(404, "Projet introuvable") from None


@app.get("/api/projects/{pid}/tree", dependencies=[Depends(auth)])
async def api_project_tree(pid: str, path: str = ""):
    return {"path": path, "entries": REG.project_tree(pid, path)}


@app.post("/api/projects/{pid}/scan", dependencies=[Depends(mutation)])
async def api_project_scan(pid: str):
    return await asyncio.to_thread(REG.scan_project, pid)


@app.post("/api/projects", dependencies=[Depends(mutation)])
async def api_create_project(payload: dict):
    pid = REG.add_project(str(payload.get("path", "")), str(payload.get("name", "")),
                          str(payload.get("client", "")), bool(payload.get("mask_name", False)))
    return {"ok": True, "id": pid}


@app.put("/api/projects/{pid}", dependencies=[Depends(mutation)])
async def api_update_project(pid: str, payload: dict):
    REG.update_project(pid, str(payload.get("name", "")), str(payload.get("client", "")),
                       bool(payload.get("mask_name", False)))
    return {"ok": True}


@app.delete("/api/projects/{pid}", dependencies=[Depends(mutation)])
async def api_delete_project(pid: str):
    REG.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/c3", dependencies=[Depends(mutation)])
async def api_project_c3(pid: str, payload: dict):
    return {"ok": True, "c3": REG.set_c3(pid, str(payload.get("path", "")), bool(payload.get("c3")))}


@app.get("/api/provider", dependencies=[Depends(auth)])
async def api_get_provider():
    return {"provider": REG.get_provider(), "providers": PROVIDERS}


@app.put("/api/provider", dependencies=[Depends(mutation)])
async def api_set_provider(payload: dict):
    return {"ok": True, "provider": REG.set_provider(str(payload.get("provider", "")))}


@app.get("/api/c3-sessions", dependencies=[Depends(auth)])
async def api_c3_sessions():
    return {"sessions": REG.c3_sessions()}


@app.post("/api/c3-sessions/{session_id}/close", dependencies=[Depends(mutation)])
async def api_close_c3_session(session_id: str):
    REG.close_c3_session(session_id)
    return {"ok": True}


@app.put("/api/settings", dependencies=[Depends(mutation)])
async def api_settings(payload: dict):
    return {"ok": True, "settings": REG.set_settings(payload)}


@app.post("/api/settings/reset", dependencies=[Depends(mutation)])
async def api_reset_settings():
    return {"ok": True, "settings": REG.reset_settings()}


@app.post("/api/preview", dependencies=[Depends(mutation)])
async def api_preview(payload: dict):
    """Montre ce qui partirait vers l'API pour un texte (via le proxy, avec la config courante)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{PROXY_URL}/_gov/preview",
                             json={"text": str(payload.get("text", ""))[:20000],
                                   "scope": payload.get("scope", "user_text")})
    except httpx.HTTPError as e:
        raise AdminError(f"Proxy injoignable : {e}") from None
    if r.status_code != 200:
        raise AdminError(f"Proxy en erreur ({r.status_code}) : {r.text[:300]}")
    return r.json()


# ------------------------------------------------------------------ journal
SHOWN_DECISIONS = {"deny", "ask", "block", "warn", "config_changed"}
SHOWN_PROXY_EVENTS = {"pii_pseudonymized", "request_blocked", "config_reloaded", "c3_blocked"}


def _tail(path: Path, n: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=n))
    except FileNotFoundError:
        return []


def _kind(e: dict) -> str:
    d, ev = e.get("decision"), e.get("event")
    if d in ("deny", "block") or ev in ("request_blocked", "c3_blocked"):
        return "deny"
    if d in ("ask", "warn"):
        return "ask"
    if ev == "pii_pseudonymized":
        return "pseudo"
    if e.get("c3"):
        return "c3"
    return "config"


def _details(e: dict) -> str:
    if e.get("event") == "settings_changed":
        return e.get("details_text", "")
    if e.get("counts"):
        return ", ".join(f"{k} × {v}" for k, v in sorted(e["counts"].items()))
    if e.get("event") == "config_reloaded":
        return f"{e.get('terms', 0)} termes dans le dictionnaire"
    if e.get("event") == "c3_blocked":
        return f"Envoi à Anthropic bloqué : {e.get('reason', '')}"
    parts = [e.get("reason") or "", e.get("target") or ""]
    if e.get("detected"):
        parts.append(", ".join(f"{k} × {v}" for k, v in sorted(e["detected"].items())))
    return " — ".join(p for p in parts if p)


SETTING_NAMES = {**{k: t for k, (t, _) in BOOL_LABELS.items()}, **{k: t for k, (t, _) in TYPE_LABELS.items()},
                 **{k: t for k, (t, _) in DECISION_LABELS.items()}, "ner_threshold": "Seuil de détection des noms",
                 "allowlist_extra": "Exceptions", "pii_tables": "Tables de données personnelles",
                 "web_deny_domains_extra": "Domaines interdits"}


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "oui" if v else "non"
    if isinstance(v, list):
        return f"{len(v)} entrée(s)"
    return {"ask": "demander", "deny": "refuser"}.get(v, str(v))


def _settings_events() -> list[dict]:
    out = []
    for h in REG.settings_history(50):
        parts = [f"{SETTING_NAMES.get(c.get('sub') or c['key'], c.get('sub') or c['key'])} : "
                 f"{_fmt(c['old'])} → {_fmt(c['new'])}" for c in h.get("changes", [])]
        prefix = ("Protection réduite — " if h.get("reduces") else "") + \
            ("Retour aux valeurs par défaut — " if h.get("action") == "reset" else "")
        out.append({"ts": h.get("ts", ""), "event": "settings_changed", "component": "console",
                    "details_text": prefix + "; ".join(parts), "reduces": h.get("reduces", False)})
    return out


def recent_events(limit: int = 100) -> list[dict]:
    events = _settings_events()
    for name in ("hooks-audit.jsonl", "proxy-audit.jsonl"):
        for line in _tail(LOG_DIR / name, 3000):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("decision") in SHOWN_DECISIONS or e.get("event") in SHOWN_PROXY_EVENTS or e.get("c3"):
                events.append(e)
    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return [{
        "ts": e.get("ts", ""),
        "kind": _kind(e),
        "label": e.get("decision") or e.get("event"),
        "tool": e.get("tool_name") or e.get("component") or "",
        "rule": e.get("rule") or "",
        "details": _details(e),
        "counts": e.get("counts") or e.get("detected") or {},
        "model": e.get("model") or "",
        "provider": e.get("provider") or "",
        "c3": bool(e.get("c3")),
    } for e in events[:limit]]


# ------------------------------------------------------------------ application React
if (WEBAPP_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEBAPP_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Route inconnue")
    candidate = (WEBAPP_DIR / path).resolve()
    if path and candidate.is_file() and WEBAPP_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = WEBAPP_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(status_code=503, content={"error": "Interface non construite (npm run build)"})
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
