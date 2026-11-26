"""Projets de code : registre de la console, chemins C3 déclarés dans les hooks et le proxy."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "admin"))

from govadmin.projects import MARKER_WORD  # noqa: E402
from govadmin.registry import AdminError, Registry  # noqa: E402

MARKER_DIR = "_" + MARKER_WORD  # dossier C3 par convention (écrit ainsi pour ne pas déclencher le hook)


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "project"
    repo = root / "interne" / "outil"
    for d in ("src", "deploy/config", "deploy/config-bis", "var/runs"):
        (repo / d).mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "src" / "main.py").write_text("print('ACME Industries')\n")
    (repo / "deploy" / "config" / "prod.yaml").write_text("password: Sup3rS3cret!\nurl: https://acme.example\n")
    (repo / "deploy" / "config-bis" / "x.yaml").write_text("password: ${PWD_FROM_ENV}\n")
    (repo / ".env").write_text("KEY=1\n")
    (root / "autre").mkdir()
    return root, repo


@pytest.fixture
def reg(tmp_path, projects):
    root, _ = projects
    return Registry(tmp_path / "config", tmp_path / "clients", root, "/home/u/project")


# ------------------------------------------------------------------ registre
def test_declare_project_and_c3_paths(reg, tmp_path):
    reg.save_client("C001", "ACME Industries", [], create=True)
    pid = reg.add_project("interne/outil", "Outil interne", "C001")
    assert pid == "outil-interne"
    assert reg.set_c3(pid, "deploy/config", True) == ["deploy/config"]
    generated = json.loads((tmp_path / "config" / "c3-paths.json").read_text())
    assert generated["paths"] == ["/home/u/project/interne/outil/deploy/config"]
    p = reg.get_project(pid)
    assert p["client_name"] == "ACME Industries" and p["host_path"] == "/home/u/project/interne/outil"


def test_candidates_stop_at_git_repos(reg):
    cands = {c["path"]: c for c in reg.project_candidates()}
    assert cands["interne/outil"]["git"] and "interne/outil/src" not in cands
    assert "autre" in cands


def test_c3_folder_replaces_descendants_and_inheritance(reg):
    pid = reg.add_project("interne/outil")
    reg.set_c3(pid, "deploy/config/prod.yaml", True)
    assert reg.set_c3(pid, "deploy", True) == ["deploy"]  # le dossier englobe le fichier
    with pytest.raises(AdminError, match="Déjà protégé"):
        reg.set_c3(pid, "deploy/config", True)
    with pytest.raises(AdminError, match="Protégé par le dossier"):
        reg.set_c3(pid, "deploy/config", False)
    tree = {e["name"]: e for e in reg.project_tree(pid, "deploy")}
    assert tree["config"]["c3"] == "inherited"
    assert {e["name"]: e["c3"] for e in reg.project_tree(pid)}["deploy"] == "declared"
    assert reg.set_c3(pid, "deploy", False) == []


def test_tree_flags_marker_and_contains(reg, projects):
    _, repo = projects
    (repo / MARKER_DIR).mkdir()
    pid = reg.add_project("interne/outil")
    reg.set_c3(pid, "deploy/config", True)
    tree = {e["name"]: e for e in reg.project_tree(pid)}
    assert tree[MARKER_DIR]["c3"] == "marker"
    assert tree["deploy"]["contains_c3"] and tree["deploy"]["c3"] is None
    assert ".git" not in tree


@pytest.mark.parametrize("bad", ["../autre", "deploy/../../autre", "/etc"])
def test_paths_cannot_escape_project(reg, bad):
    pid = reg.add_project("interne/outil")
    with pytest.raises(AdminError):
        reg.set_c3(pid, bad, True) if not bad.startswith("/") else reg.project_tree(pid, "../../..")


def test_whole_project_cannot_be_c3(reg):
    pid = reg.add_project("interne/outil")
    with pytest.raises(AdminError, match="projet entier"):
        reg.set_c3(pid, "", True)


def test_overlapping_and_unknown_projects_refused(reg):
    reg.add_project("interne/outil")
    with pytest.raises(AdminError, match="chevauche"):
        reg.add_project("interne")
    with pytest.raises(AdminError, match="introuvable"):
        reg.add_project("nexiste/pas")
    with pytest.raises(AdminError, match="non déclaré"):
        reg.add_project("autre", client="C999")


def test_masked_project_name_in_terms(reg, tmp_path):
    reg.add_project("interne/outil", "Projet Hermès", mask_name=True)
    terms = json.loads((tmp_path / "config" / "terms.json").read_text())
    assert "Projet Hermès" in terms["PROJET"]


def test_client_in_use_cannot_be_deleted(reg):
    reg.save_client("C001", "ACME Industries", [], create=True)
    reg.add_project("interne/outil", client="C001")
    with pytest.raises(AdminError, match="associé aux projets"):
        reg.delete_client("C001")


def test_scan(reg):
    reg.save_client("C001", "ACME Industries", ["acme.example"], create=True)
    pid = reg.add_project("interne/outil")
    reg.set_c3(pid, "deploy/config", True)
    r = reg.scan_project(pid)
    terms = {t["term"]: t for t in r["terms"]}
    assert terms["ACME Industries"]["samples"] == [{"path": "src/main.py", "c3": None}]
    assert terms["acme.example"]["samples"][0]["c3"] == "inherited"
    assert r["secret_files"] == [{"path": ".env", "c3": None}]
    creds = [(c["path"], c["c3"]) for c in r["credentials"]]
    assert creds == [("deploy/config/prod.yaml", "inherited")]  # ${VAR} ignoré
    assert "Sup3rS3cret" not in json.dumps(r)  # aucune valeur renvoyée


def test_scan_flags_client_name_in_path(reg, projects, tmp_path):
    root, _ = projects
    (root / "acme-portail").mkdir()
    reg.save_client("C001", "ACME", [], create=True)
    pid = reg.add_project("acme-portail")
    assert reg.scan_project(pid)["path_terms"] == ["ACME"]


# ------------------------------------------------------------------ hooks
def _hook(tool, tin, cwd, tmp_path, c3=(), provider="claude"):
    cfg = tmp_path / "hookcfg"
    cfg.mkdir(exist_ok=True)
    (cfg / "overrides.json").write_text(json.dumps({"provider": provider}))
    (cfg / "c3-paths.json").write_text(json.dumps({"paths": [str(p) for p in c3]}))
    env = {**os.environ, "CLAUDE_GOV_POLICY": str(ROOT / "policy" / "policy.json"),
           "CLAUDE_GOV_CONFIG_DIR": str(cfg), "CLAUDE_GOV_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard_tool.py")],
                       input=json.dumps({"session_id": "s1", "cwd": str(cwd), "tool_name": tool, "tool_input": tin}),
                       capture_output=True, text=True, env=env, timeout=20)
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    return out.get("hookSpecificOutput", {}), cfg


@pytest.mark.parametrize("tool,tin,cwd_rel", [
    ("Read", {"file_path": "{repo}/deploy/config/prod.yaml"}, ""),
    ("Read", {"file_path": "deploy/config/prod.yaml"}, ""),                 # relatif au répertoire de travail
    ("Read", {"file_path": "../config/prod.yaml"}, "deploy/config-bis"),
    ("Edit", {"file_path": "prod.yaml", "old_string": "a", "new_string": "b"}, "deploy/config"),
    ("Bash", {"command": "cat deploy/config/prod.yaml"}, ""),
    ("Bash", {"command": "cd deploy && cat config/*.yaml"}, ""),
    ("Bash", {"command": "ls config"}, "deploy"),                           # mot sans / ni .
    ("Bash", {"command": "grep -rn password ."}, ""),                       # récursif sur un parent
    ("Bash", {"command": "rg password"}, ""),                               # récursif, dossier implicite
    ("Grep", {"pattern": "password"}, ""),                                  # Grep sans chemin = cwd
    ("Grep", {"pattern": "password", "path": "{repo}/deploy"}, ""),
    ("Glob", {"pattern": "*.yaml", "path": "{repo}/deploy/config"}, ""),
])
def test_declared_c3_denied_with_claude(tool, tin, cwd_rel, projects, tmp_path):
    _, repo = projects
    tin = {k: v.replace("{repo}", str(repo)) for k, v in tin.items()}
    out, cfg = _hook(tool, tin, repo / cwd_rel, tmp_path, c3=[repo / "deploy" / "config"])
    assert out.get("permissionDecision") == "deny", (tool, tin)
    assert "C3" in out["permissionDecisionReason"]
    assert not (cfg / "c3-sessions.json").exists()


@pytest.mark.parametrize("tool,tin", [
    ("Read", {"file_path": "src/main.py"}),
    ("Read", {"file_path": "deploy/config-bis/x.yaml"}),   # préfixe proche, autre dossier
    ("Bash", {"command": "grep -rn password src"}),         # récursif mais hors C3
    ("Grep", {"pattern": "password", "path": "src"}),
    ("Glob", {"pattern": "**/*.py"}),                        # noms seulement
])
def test_non_c3_paths_still_allowed(tool, tin, projects, tmp_path):
    _, repo = projects
    out, _ = _hook(tool, tin, repo, tmp_path, c3=[repo / "deploy" / "config"])
    assert out.get("permissionDecision") is None, (tool, tin, out)


def test_declared_c3_allowed_with_trusted_and_session_marked(projects, tmp_path):
    _, repo = projects
    out, cfg = _hook("Read", {"file_path": "deploy/config/prod.yaml"}, repo, tmp_path,
                     c3=[repo / "deploy" / "config"], provider="trusted")
    assert out.get("permissionDecision") is None
    assert json.loads((cfg / "c3-sessions.json").read_text())["s1"]["accesses"] == 1


def test_recursive_search_over_marker_folder_denied(projects, tmp_path):
    """Corrige l'ancien trou : grep -r depuis un parent n'écrit pas le nom du dossier C3."""
    _, repo = projects
    (repo / "docs" / MARKER_DIR).mkdir(parents=True)
    for tool, tin in (("Bash", {"command": "grep -r marge docs"}), ("Grep", {"pattern": "marge", "path": "docs"})):
        out, _ = _hook(tool, tin, repo, tmp_path)
        assert out.get("permissionDecision") == "deny", tool


def test_corrupt_c3_paths_fails_closed(projects, tmp_path):
    _, repo = projects
    cfg = tmp_path / "hookcfg"
    _hook("Read", {"file_path": "src/main.py"}, repo, tmp_path)
    (cfg / "c3-paths.json").write_text("{ illisible")
    env = {**os.environ, "CLAUDE_GOV_POLICY": str(ROOT / "policy" / "policy.json"),
           "CLAUDE_GOV_CONFIG_DIR": str(cfg), "CLAUDE_GOV_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard_tool.py")],
                       input=json.dumps({"cwd": str(repo), "tool_name": "Read", "tool_input": {"file_path": "src/main.py"}}),
                       capture_output=True, text=True, env=env, timeout=20)
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# ------------------------------------------------------------------ API de la console
@pytest.fixture
def api(tmp_path, monkeypatch, projects):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    root, _ = projects
    webapp = tmp_path / "webapp"
    webapp.mkdir()
    (webapp / "index.html").write_text("<!doctype html>")
    for k, v in {"ADMIN_PASSWORD": "mot-de-passe-de-test", "GOV_CONFIG_DIR": str(tmp_path / "config"),
                 "CLIENTS_DIR": str(tmp_path / "clients"), "GOV_LOG_DIR": str(tmp_path / "logs"),
                 "PROXY_URL": "http://127.0.0.1:9", "WEBAPP_DIR": str(webapp),
                 "PROJECTS_DIR": str(root), "HOST_PROJECTS_DIR": "/home/u/project"}.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("govadmin.main", None)
    import govadmin.main
    c = TestClient(govadmin.main.app)
    assert c.post("/api/session", json={"password": "mot-de-passe-de-test"}).status_code == 200
    c.headers["X-Gov-Admin"] = "1"
    return c


def test_api_project_flow(api, tmp_path):
    assert api.get("/api/projects/candidates").json()["root"] == "/home/u/project"
    r = api.post("/api/projects", json={"path": "interne/outil", "name": "Outil"})
    pid = r.json()["id"]
    assert api.post(f"/api/projects/{pid}/c3", json={"path": "deploy/config", "c3": True}).json()["c3"] == ["deploy/config"]
    detail = api.get(f"/api/projects/{pid}").json()
    assert detail["command"] == "cd /home/u/project/interne/outil && claude"
    tree = api.get(f"/api/projects/{pid}/tree", params={"path": "deploy"}).json()["entries"]
    assert {e["name"]: e["c3"] for e in tree}["config"] == "declared"
    assert api.post(f"/api/projects/{pid}/scan").status_code == 200
    assert api.post(f"/api/projects/{pid}/c3", json={"path": "../../..", "c3": True}).status_code == 400
    assert api.delete(f"/api/projects/{pid}").status_code == 200
    assert json.loads((tmp_path / "config" / "c3-paths.json").read_text())["paths"] == []


def test_api_project_mutation_needs_csrf_header(api):
    del api.headers["X-Gov-Admin"]
    assert api.post("/api/projects", json={"path": "autre"}).status_code == 403
