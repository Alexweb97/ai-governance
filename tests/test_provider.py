"""Bascule de fournisseur (Claude / fournisseur de confiance) dans le proxy, avec un faux serveur fournisseur de confiance."""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("prometheus_client")
    import httpx
    from fastapi.testclient import TestClient

    policy = json.loads((ROOT / "policy" / "policy.json").read_text())
    policy["pii"]["presidio"]["enabled"] = False
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "overrides.json").write_text(json.dumps({"provider": "trusted"}))
    (cfg / "terms.json").write_text(json.dumps({"CLIENT": ["ACME Industries"]}))
    for k, v in {"POLICY_PATH": str(tmp_path / "policy.json"), "GOV_CONFIG_DIR": str(cfg),
                 "AUDIT_LOG": str(tmp_path / "audit.jsonl"), "PSEUDO_SECRET": "s" * 64,
                 "TRUSTED_API_KEY": "cle-confiance-de-test", "TRUSTED_MODEL": "modele-local",
                 "TRUSTED_URL": "https://llm.test", "TRUSTED_NAME": "LLM de test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("REDIS_URL", raising=False)
    from prometheus_client import REGISTRY
    for col, names in list(REGISTRY._collector_to_names.items()):  # métriques d'un import précédent
        if any(n.startswith("gov_") for n in names):
            REGISTRY.unregister(col)
    for m in [m for m in sys.modules if m.startswith("app.") and m != "app.pii"]:
        del sys.modules[m]
    main = importlib.import_module("app.main")

    seen = {}

    def fake_trusted(request: httpx.Request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        if seen["body"].get("stream"):
            events = [
                {"type": "message_start", "message": {"id": "m", "content": [], "role": "assistant"}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Bonjour " + seen["token"]}},
                {"type": "text", "text": "Bonjour", "snapshot": "Bonjour " + seen["token"]},
                {"type": "content_block_stop", "index": 0, "content_block": {"type": "text", "text": "Bonjour " + seen["token"]}},
                {"type": "message_stop", "message": {"content": [{"type": "text", "text": seen["token"]}]}},
            ]
            sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
            return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"type": "message", "content": [{"type": "text", "text": "ok"}]})

    with TestClient(main.app) as c:
        main.app.state.trusted = httpx.AsyncClient(base_url="https://llm.test", transport=httpx.MockTransport(fake_trusted))
        seen["token"] = main.RUNTIME.get().pseudo.token_for("CLIENT", "ACME Industries")
        yield c, main, seen


def test_trusted_never_receives_claude_credentials(proxy):
    c, _, seen = proxy
    r = c.post("/v1/messages?beta=true", headers={"authorization": "Bearer jeton-claude-pro",
                                                  "x-api-key": "cle-anthropic", "anthropic-beta": "oauth-2025-04-20",
                                                  "anthropic-version": "2023-06-01"},
               json={"model": "claude-opus-5-5", "max_tokens": 10,
                     "messages": [{"role": "user", "content": "Offre pour ACME Industries"}]})
    assert r.status_code == 200
    h = seen["headers"]
    assert h["x-api-key"] == "cle-confiance-de-test"
    assert "authorization" not in h and "anthropic-beta" not in h
    assert "jeton-claude-pro" not in json.dumps(h) and "cle-anthropic" not in json.dumps(h)
    assert seen["body"]["model"] == "modele-local"
    assert "ACME" not in json.dumps(seen["body"])  # pseudonymisé aussi vers le fournisseur de confiance


def test_trusted_bearer_auth(proxy, monkeypatch):
    c, main, seen = proxy
    monkeypatch.setattr(main, "TRUSTED_AUTH", "bearer")
    r = c.post("/v1/messages", headers={"authorization": "Bearer jeton-claude-pro"},
               json={"model": "claude-opus-5-5", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    assert seen["headers"]["authorization"] == "Bearer cle-confiance-de-test"
    assert "x-api-key" not in seen["headers"]


@pytest.mark.parametrize("missing", ["TRUSTED_URL", "TRUSTED_MODEL", "TRUSTED_API_KEY"])
def test_trusted_incomplete_config_refused(proxy, monkeypatch, missing):
    c, main, seen = proxy
    monkeypatch.setattr(main, missing, "")
    r = c.post("/v1/messages", json={"model": "claude-opus-5-5", "max_tokens": 10,
                                     "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 503 and missing in r.json()["error"]["message"]
    assert "LLM de test" in r.json()["error"]["message"]
    assert "body" not in seen  # rien n'est parti, ni vers le fournisseur de confiance ni vers Anthropic


def test_trusted_stream_is_standard_and_rehydrated(proxy):
    c, _, seen = proxy
    r = c.post("/v1/messages", json={"model": "claude-opus-5-5", "max_tokens": 10, "stream": True,
                                     "messages": [{"role": "user", "content": "Salue ACME Industries"}]})
    frames = [json.loads(l[5:]) for l in r.text.split("\n") if l.startswith("data:")]
    types = [f["type"] for f in frames]
    assert set(types) == {"message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_stop"}
    assert frames[-2] == {"type": "content_block_stop", "index": 0} and frames[-1] == {"type": "message_stop"}
    text = "".join(f["delta"]["text"] for f in frames if f["type"] == "content_block_delta")
    assert text == "Bonjour ACME Industries" and seen["token"] not in r.text  # copies non ré-identifiées retirées


def test_trusted_count_tokens_answered_locally(proxy):
    c, _, seen = proxy
    r = c.post("/v1/messages/count_tokens", json={"model": "claude-opus-5-5", "messages": [{"role": "user", "content": "x" * 400}]})
    assert r.status_code == 200 and r.json()["input_tokens"] > 50 and "body" not in seen


def test_switch_back_to_claude_hot(proxy, tmp_path):
    c, main, _ = proxy
    (tmp_path / "cfg" / "overrides.json").write_text(json.dumps({"provider": "claude"}))
    main.RUNTIME._checked = 0  # force la relecture
    assert main.RUNTIME.get().provider == "claude"
    assert c.get("/healthz").json()["provider"] == "claude"


# ------------------------------------------------------------------ verrou C3 côté proxy
def _claude_mode(main, tmp_path, c3=None):
    cfg = tmp_path / "cfg"
    (cfg / "overrides.json").write_text(json.dumps({"provider": "claude"}))
    if c3 is not None:
        (cfg / "c3-sessions.json").write_text(c3 if isinstance(c3, str) else json.dumps(c3))
    main.RUNTIME._checked = 0
    assert main.RUNTIME.get().provider == "claude"


def _msg(c, session="s-propre", history=None):
    return c.post("/v1/messages", headers={"x-claude-code-session-id": session},
                  json={"model": "claude-opus-5-5", "max_tokens": 5,
                        "messages": history or [{"role": "user", "content": "bonjour"}]})


def test_c3_session_never_sent_to_anthropic(proxy, tmp_path):
    c, main, _ = proxy
    _claude_mode(main, tmp_path, {"sess-c3": {"opened": "x", "ended": "y"}})  # même terminée
    r = _msg(c, session="sess-c3")
    assert r.status_code == 400 and "C3" in r.json()["error"]["message"]


def test_c3_history_marker_blocked_even_without_registry(proxy, tmp_path):
    c, main, _ = proxy
    _claude_mode(main, tmp_path)
    history = [{"role": "user", "content": "lis le BPU"},
               {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash",
                                                  "input": {"command": "cat ../_confidentiel/BPU.csv"}}]},
               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "..."}]}]
    assert _msg(c, session="nouvelle", history=history).status_code == 400


def test_c3_registry_corrupt_fail_closed(proxy, tmp_path):
    c, main, _ = proxy
    _claude_mode(main, tmp_path, "{ illisible")
    assert _msg(c).status_code == 400


def test_c3_session_allowed_on_trusted(proxy, tmp_path):
    c, main, seen = proxy  # fixture : fournisseur trusted
    (tmp_path / "cfg" / "c3-sessions.json").write_text(json.dumps({"sess-c3": {"ended": None}}))
    r = _msg(c, session="sess-c3")
    assert r.status_code == 200 and seen["headers"]["x-api-key"] == "cle-confiance-de-test"


def test_denied_c3_attempt_does_not_lock_session(proxy, tmp_path):
    c, main, _ = proxy
    _claude_mode(main, tmp_path)
    history = [{"role": "user", "content": "lis le BPU"},
               {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Read",
                                                  "input": {"file_path": "../_confidentiel/BPU.csv"}}]},
               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "is_error": True,
                                             "content": "[Gouvernance] Contenu C3 : lisible uniquement avec fournisseur de confiance"}]}]
    r = _msg(c, session="nouvelle", history=history)
    assert r.status_code != 400  # tentative refusée : rien n'a été lu, la session reste utilisable


# ------------------------------------------------------------------ chemins C3 déclarés (écran Projets)
def _history(command):
    return [{"role": "user", "content": "lis la config"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": command}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "..."}]}]


def test_declared_c3_path_in_history_blocked(proxy, tmp_path):
    c, main, _ = proxy
    (tmp_path / "cfg" / "c3-paths.json").write_text(json.dumps({"paths": ["/home/u/project/outil/deploy/config"]}))
    _claude_mode(main, tmp_path)
    r = _msg(c, session="nouvelle", history=_history("cat /home/u/project/outil/deploy/config/prod.yaml"))
    assert r.status_code == 400 and "déclaré C3" in r.json()["error"]["message"]


def test_declared_c3_path_prefix_not_confused(proxy, tmp_path):
    c, main, _ = proxy
    (tmp_path / "cfg" / "c3-paths.json").write_text(json.dumps({"paths": ["/home/u/project/outil/deploy/config"]}))
    _claude_mode(main, tmp_path)
    r = _msg(c, session="nouvelle", history=_history("cat /home/u/project/outil/deploy/config-bis/x.yaml"))
    assert r.status_code != 400
