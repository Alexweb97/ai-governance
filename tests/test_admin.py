"""Tests de la console d'administration : registre (stdlib) et application web (si FastAPI présent)."""
import base64
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "admin"))

from govadmin.registry import PROVIDERS, AdminError, Registry  # noqa: E402


@pytest.fixture
def reg(tmp_path):
    return Registry(tmp_path / "config", tmp_path / "clients")


# ------------------------------------------------------------------ registre
def test_client_and_terms(reg):
    assert reg.next_code() == "C001"
    reg.save_client("C001", "ACME Industries", "ACME\nSociété ACME\n acme \nA", create=True)
    terms = json.loads(reg.terms_path.read_text())
    assert terms["CLIENT"] == ["ACME Industries", "ACME", "Société ACME"]  # doublons et termes < 2 car. retirés
    assert (reg.clients_dir / "C001").is_dir()
    assert reg.next_code() == "C002"
    with pytest.raises(AdminError):
        reg.save_client("C001", "Autre", "", create=True)
    with pytest.raises(AdminError):
        reg.save_client("../x", "Autre", "", create=True)


def test_consultation_structure_and_project_terms(reg):
    reg.save_client("C001", "ACME", "", create=True)
    reg.add_consultation("C001", "AO-2026-015", "Refonte du SI")
    d = reg.clients_dir / "C001" / "AO-2026-015"
    assert (d / "travail" / "DCE").is_dir() and (d / "travail" / "memoire-technique").is_dir()
    assert (d / "_confidentiel").is_dir()
    assert json.loads(reg.terms_path.read_text())["PROJET"] == ["Refonte du SI"]
    with pytest.raises(AdminError):
        reg.add_consultation("C001", "AO-2026-015", "")
    with pytest.raises(AdminError):
        reg.add_consultation("C999", "AO-1", "")  # client non déclaré


def test_files_upload_move_delete(reg):
    reg.save_client("C001", "ACME", "", create=True)
    reg.add_consultation("C001", "AO-1")
    p = reg.save_upload("C001", "AO-1", "dce", "C:\\Users\\x\\CCTP.pdf", io.BytesIO(b"%PDF"))
    assert p == "travail/DCE/CCTP.pdf"
    assert reg.save_upload("C001", "AO-1", "dce", "CCTP.pdf", io.BytesIO(b"x")) == "travail/DCE/CCTP (1).pdf"
    reg.save_upload("C001", "AO-1", "confidentiel", "BPU.xlsx", io.BytesIO(b"x"))
    levels = {f["path"]: f["level"] for f in reg.list_files("C001", "AO-1")}
    assert levels == {"travail/DCE/CCTP.pdf": "C2", "travail/DCE/CCTP (1).pdf": "C2",
                      "_confidentiel/BPU.xlsx": "C3"}
    assert reg.move_file("C001", "AO-1", "travail/DCE/CCTP.pdf", "confidentiel") == "_confidentiel/CCTP.pdf"
    reg.delete_file("C001", "AO-1", "_confidentiel/CCTP.pdf")
    assert not (reg.clients_dir / "C001/AO-1/_confidentiel/CCTP.pdf").exists()
    for bad in ("../../config/clients.json", "/etc/passwd", "../AO-2/x"):
        with pytest.raises(AdminError):
            reg.delete_file("C001", "AO-1", bad)
    with pytest.raises(AdminError):
        reg.save_upload("C001", "AO-1", "../../", "x", io.BytesIO(b""))


def test_undeclared_folders_listed(reg):
    (reg.clients_dir / "ACME").mkdir(parents=True)
    clients = reg.list_clients()
    assert clients[0]["code"] == "ACME" and clients[0]["declared"] is False


def test_legacy_terms_kept(reg):
    reg.config_dir.mkdir(parents=True)
    reg.terms_path.write_text(json.dumps({"CLIENT": ["Ancien Client"], "INTERNE": ["Projet X"]}))
    reg.save_client("C001", "ACME", "", create=True)
    terms = json.loads(reg.terms_path.read_text())
    assert terms["CLIENT"] == ["ACME", "Ancien Client"] and terms["INTERNE"] == ["Projet X"]


def test_settings(reg):
    s = reg.get_settings()
    assert (s["mask_amounts"], s["allow_images"], s["ner_documents"]) == (True, False, True)
    with pytest.raises(AdminError, match="inconnu"):
        reg.set_settings({"mask_amounts": False, "unknown": True})
    reg.set_settings({"mask_amounts": False})
    assert json.loads(reg.overrides_path.read_text()) == {"mask_amounts": False}


# ------------------------------------------------------------------ application web
@pytest.fixture
def web(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    webapp = tmp_path / "webapp"
    (webapp / "assets").mkdir(parents=True)
    (webapp / "index.html").write_text("<!doctype html><div id=root></div>")
    (webapp / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("ADMIN_PASSWORD", "mot-de-passe-de-test")
    monkeypatch.setenv("GOV_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CLIENTS_DIR", str(tmp_path / "clients"))
    monkeypatch.setenv("GOV_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("WEBAPP_DIR", str(webapp))
    sys.modules.pop("govadmin.main", None)
    import govadmin.main

    return TestClient(govadmin.main.app)


@pytest.fixture
def client(web):
    assert web.post("/api/session", json={"password": "mot-de-passe-de-test"}).status_code == 200
    return web


def test_session_flow(web):
    assert web.get("/api/session").json() == {"authenticated": False}
    assert web.get("/api/clients").status_code == 401
    assert web.post("/api/session", json={"password": "faux"}).status_code == 401
    r = web.post("/api/session", json={"password": "mot-de-passe-de-test"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert web.get("/api/clients").status_code == 200
    web.delete("/api/session")
    assert web.get("/api/clients").status_code == 401


def test_forged_session_rejected(web):
    web.cookies.set("gov_session", base64.urlsafe_b64encode(b"9999999999.abc.deadbeef").decode())
    assert web.get("/api/clients").status_code == 401


def test_csrf(client):
    assert client.post("/api/clients", json={"code": "C001", "name": "ACME"}).status_code == 403
    r = client.post("/api/clients", json={"code": "C001", "name": "ACME"},
                    headers={"X-Gov-Admin": "1", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_full_flow(client):
    h = {"X-Gov-Admin": "1"}
    assert client.post("/api/clients", json={"code": "C001", "name": "ACME", "variants": ["Société ACME"]},
                       headers=h).json() == {"ok": True, "code": "C001"}
    assert client.post("/api/clients", json={"code": "C001", "name": "X"}, headers=h).json()["error"]
    assert client.post("/api/clients/C001/consultations", json={"ref": "AO-1", "title": "Refonte"},
                       headers=h).json()["ref"] == "AO-1"
    r = client.post("/api/clients/C001/AO-1/files", data={"dest": "dce"},
                    files=[("files", ("CCTP.pdf", b"%PDF", "application/pdf"))], headers=h)
    assert r.json()["saved"] == ["travail/DCE/CCTP.pdf"]
    assert client.put("/api/settings", json={"mask_amounts": False}, headers=h).json()["settings"]["mask_amounts"] is False

    clients = client.get("/api/clients").json()
    assert clients["next_code"] == "C002" and clients["clients"][0]["variants"] == ["Société ACME"]
    detail = client.get("/api/clients/C001/AO-1").json()
    assert detail["files"][0]["path"] == "travail/DCE/CCTP.pdf"
    assert detail["command"].endswith("C001/AO-1/travail && claude")
    assert client.get("/api/settings").json()["settings"]["mask_amounts"] is False
    status = client.get("/api/status").json()
    assert status["health"]["ok"] is False and status["clients"]["declared"] == 1  # proxy absent du test
    assert client.get("/api/clients/C999").status_code == 404


def test_spa_served(client):
    for path in ("/", "/clients/C001/AO-1", "/reglages"):
        r = client.get(path)
        assert r.status_code == 200 and "<div id=root>" in r.text
        assert "script-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/inconnu").status_code == 404
    assert client.get("/../../etc/passwd").status_code in (200, 404)  # jamais le fichier
    assert "root:" not in client.get("/..%2f..%2fetc/passwd").text


def test_provider_setting(reg):
    assert reg.get_provider() == "claude"
    reg.set_settings({"mask_amounts": False})
    assert reg.set_provider("trusted") == "trusted"
    ov = json.loads(reg.overrides_path.read_text())
    assert ov["provider"] == "trusted" and ov["mask_amounts"] is False  # les deux réglages cohabitent
    assert ov["provider_label"] == PROVIDERS["trusted"]["name"]  # recopié pour les hooks
    reg.set_settings({"allow_images": True})
    assert reg.get_provider() == "trusted"
    with pytest.raises(AdminError):
        reg.set_provider("autre")


def test_switch_to_claude_blocked_by_open_c3_session(reg):
    from datetime import datetime, timezone
    reg.set_provider("trusted")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg.c3_path.write_text(json.dumps({"abcdef1234": {"opened": now, "last": now, "ended": None, "accesses": 2}}))
    assert [s["open"] for s in reg.c3_sessions()] == [True]
    with pytest.raises(AdminError, match="C3"):
        reg.set_provider("claude")
    reg.close_c3_session("abcdef1234")
    assert reg.set_provider("claude") == "claude"
    assert json.loads(reg.c3_path.read_text())["abcdef1234"]["ended"]  # conservée : reste bloquée


def test_idle_c3_session_not_blocking(reg):
    reg.c3_path.parent.mkdir(parents=True, exist_ok=True)
    reg.c3_path.write_text(json.dumps({"old": {"opened": "2020-01-01T00:00:00+00:00", "last": "2020-01-01T00:00:00+00:00", "ended": None}}))
    assert reg.c3_sessions()[0]["open"] is False
    assert reg.set_provider("claude") == "claude"
