"""Réglages de la console : validation, effet sur la politique (proxy et hooks), historique."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "admin"))
sys.path.insert(0, str(ROOT / "proxy" / "app"))

from govadmin.registry import AdminError, Registry  # noqa: E402
from pii import Detector, apply_overrides  # noqa: E402

POLICY = ROOT / "policy" / "policy.json"


@pytest.fixture
def reg(tmp_path):
    return Registry(tmp_path / "config", tmp_path / "clients", policy_path=POLICY)


def effective(reg):
    return apply_overrides(json.loads(POLICY.read_text()), json.loads(reg.overrides_path.read_text()))


def test_defaults_come_from_policy(reg):
    d = reg.default_settings()
    assert d["mask_types"]["EMAIL"] is True and d["mask_types"]["IPV4"] is False
    assert d["ner_threshold"] == 0.75 and d["decisions"]["write_secret_decision"] == "ask"
    assert "customers" in d["pii_tables"]
    assert reg.get_settings() == d


def test_mask_types_applied_and_secrets_untouchable(reg):
    reg.set_settings({"mask_types": {"EMAIL": False, "IPV4": True}})
    det = Detector(effective(reg)["pii"])
    email = "jean.dupont" + chr(64) + "societe.fr"  # construit : jamais pseudonymisé en transit
    types = {s.type for s in det.detect(f"mail {email} serveur 10.20.30.40 cle sk-ant-api03-" + "x" * 40)}
    assert "EMAIL" in {s.type for s in Detector(json.loads(POLICY.read_text())["pii"]).detect(email)}
    assert "EMAIL" not in types and "IPV4" in types and any(t.startswith("SECRET_") for t in types)
    with pytest.raises(AdminError):
        reg.set_settings({"mask_types": {"SECRET_ANTHROPIC": False}})
    assert reg.get_settings()["mask_types"]["PHONE_FR"] is True  # fusion partielle


def test_ner_scope_and_threshold(reg):
    reg.set_settings({"ner_tool_results": True, "ner_threshold": 0.6})
    pres = effective(reg)["pii"]["presidio"]
    assert "tool_result" in pres["scopes"] and pres["score_threshold"] == 0.6
    with pytest.raises(AdminError):
        reg.set_settings({"ner_threshold": 2})


def test_allowlist_cannot_unmask_dictionary_terms(reg):
    reg.save_client("C001", "ACME Industries", ["ACME"], create=True)
    with pytest.raises(AdminError, match="dictionnaire"):
        reg.set_settings({"allowlist_extra": ["acme"]})
    reg.set_settings({"allowlist_extra": ["Toulouse"]})
    pii = effective(reg)["pii"]
    assert "Toulouse" in pii["allowlist"] and "localhost" in pii["allowlist"]  # base conservée


def test_decisions_tables_domains(reg):
    reg.set_settings({"decisions": {"write_secret_decision": "deny"}, "pii_tables": ["patients", "crm_contacts"],
                      "web_deny_domains_extra": ["Exfil.Example.com"]})
    tg = effective(reg)["tool_guard"]
    assert tg["write_secret_decision"] == "deny" and tg["bash_network_pii_decision"] == "ask"
    assert tg["pii_tables"] == ["patients", "crm_contacts"]
    assert "exfil.example.com" in tg["web_deny_domains"] and "pastebin.com" in tg["web_deny_domains"]
    for bad in ({"decisions": {"write_secret_decision": "allow"}}, {"pii_tables": ["drop table;"]},
                {"web_deny_domains_extra": ["pas un domaine"]}, {"decisions": {"fail_mode": "deny"}}):
        with pytest.raises(AdminError):
            reg.set_settings(bad)


def test_history_and_reset(reg):
    reg.set_settings({"mask_amounts": False})
    reg.set_settings({"decisions": {"pii_tables_decision": "deny"}})
    reg.set_settings({"mask_amounts": False})  # sans changement : pas d'entrée
    h = reg.settings_history()
    assert len(h) == 2 and h[1]["reduces"] is True and h[0]["reduces"] is False
    reg.overrides_path.write_text(json.dumps({**json.loads(reg.overrides_path.read_text()), "provider": "trusted"}))
    reg.reset_settings()
    assert json.loads(reg.overrides_path.read_text()) == {"provider": "trusted"}
    assert reg.settings_history()[0]["action"] == "reset"


def test_legacy_flat_overrides_still_read(reg):
    reg.overrides_path.parent.mkdir(parents=True)
    reg.overrides_path.write_text(json.dumps({"mask_amounts": False, "allow_images": True, "ner_documents": False}))
    s = reg.get_settings()
    assert (s["mask_amounts"], s["allow_images"], s["ner_documents"]) == (False, True, False)


def test_hook_uses_console_decision(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "overrides.json").write_text(json.dumps({"decisions": {"pii_tables_decision": "deny"}}))
    env = {**os.environ, "CLAUDE_GOV_POLICY": str(POLICY), "CLAUDE_GOV_CONFIG_DIR": str(cfg),
           "CLAUDE_GOV_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard_tool.py")],
                       input=json.dumps({"cwd": "/tmp", "tool_name": "Bash",
                                         "tool_input": {"command": "psql -c 'SELECT * FROM patients'"}}),
                       capture_output=True, text=True, env=env, timeout=20)
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_api_settings(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient
    webapp = tmp_path / "webapp"
    webapp.mkdir()
    (webapp / "index.html").write_text("<!doctype html>")
    pwd = "p" * 20
    for k, v in {"ADMIN_PASSWORD": pwd, "GOV_CONFIG_DIR": str(tmp_path / "config"),
                 "CLIENTS_DIR": str(tmp_path / "clients"), "GOV_LOG_DIR": str(tmp_path / "logs"),
                 "PROXY_URL": "http://127.0.0.1:9", "WEBAPP_DIR": str(webapp), "POLICY_PATH": str(POLICY)}.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("govadmin.main", None)
    import govadmin.main
    c = TestClient(govadmin.main.app)
    assert c.post("/api/session", json={"password": pwd}).status_code == 200
    c.headers["X-Gov-Admin"] = "1"
    r = c.get("/api/settings").json()
    assert r["policy_loaded"] and "pastebin.com" in r["locked"]["web_deny_domains"] and "EMAIL" in r["type_labels"]
    assert c.put("/api/settings", json={"mask_types": {"SIRET": False}}).status_code == 200
    assert c.put("/api/settings", json={"ner_threshold": "x"}).status_code == 400
    assert c.get("/api/settings").json()["history"][0]["changes"][0]["sub"] == "SIRET"
    assert c.post("/api/settings/reset").json()["settings"]["mask_types"]["SIRET"] is True
    events = govadmin.main.recent_events()
    assert events and events[0]["label"] == "settings_changed" and "SIRET" in events[-1]["details"]
