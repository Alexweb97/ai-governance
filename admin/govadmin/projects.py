"""
Projets de code déclarés dans la console (dépôts sous ~/project, montés en lecture seule).

Un projet a un client associé (ou « interne ») et une liste de chemins C3 déclarés, relatifs à sa
racine. Les fichiers ne sont jamais déplacés ni renommés : la console génère c3-paths.json (chemins
absolus côté hôte), lu par les hooks et le proxy en plus du marqueur C3 de policy.json.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Optional

MARKER_WORD = "confidentiel"
# Même convention que tool_guard.c3_marker_regex (policy.json), appliquée à un nom de fichier ou dossier.
MARKER_NAME_RE = re.compile(rf"^_{MARKER_WORD}$|\.{MARKER_WORD}\.", re.IGNORECASE)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", "dist", "build", ".next", ".cache", ".tox", "coverage", ".idea", ".gradle", "target"}
MAX_TREE_ENTRIES = 500
CANDIDATE_DEPTH = 4  # on s'arrête de toute façon au premier dépôt git

# Analyse : limites pour rester rapide sur un gros dépôt
SCAN_MAX_FILES = 20000
SCAN_MAX_FILE_BYTES = 1024 * 1024
SCAN_MAX_TOTAL_BYTES = 150 * 1024 * 1024
SCAN_MAX_SAMPLES = 8
SCAN_MAX_CREDENTIALS = 100
SECRET_FILE_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
                        "*.tfstate", "*.tfstate.backup", "credentials.json", "*.kdbx", ".netrc", ".pgpass")
SECRET_FILE_EXCEPTIONS = {".env.example", ".env.sample", ".env.template", ".env.dist"}
# Identifiant écrit en dur. Ignore les références (${VAR}, <...>, {{ }}, %s) : la valeur n'est jamais renvoyée.
CREDENTIAL_RE = re.compile(
    r"""(?i)(?<![a-z])(password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret)["']?\s*[:=]\s*(["']?)"""
    r"""(?!\$|<|\{|%|changeme|xxx|\*|os\.|process\.env|getenv|env\[)([^\s"'#,;]{6,})""")
# In source code, only a quoted literal is a hard-coded credential: `secret = load()` is code, not a value.
CONFIG_SUFFIXES = {".yaml", ".yml", ".ini", ".cfg", ".conf", ".properties", ".toml", ".env", ".txt", ".xml", ".tf",
                   ".tfvars", ".sh", ".bash", ".zsh", ".ps1", ".sql", ""}


def credential_match(line: str, filename: str):
    """Match of a hard-coded credential in a line, or None. Never returns the value to callers that report."""
    m = CREDENTIAL_RE.search(line)
    if not m:
        return None
    if not m.group(2) and Path(filename).suffix.lower() not in CONFIG_SUFFIXES:
        return None
    return m


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:48] or "projet"


def norm_rel(rel: str) -> str:
    """Chemin relatif propre (posix, sans '.', sans '/' de tête, '..' refusé). '' = racine."""
    rel = str(rel or "").replace("\\", "/").strip().strip("/")
    parts = [p for p in PurePosixPath(rel).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("Chemin invalide")
    return "/".join(parts)


def covers(parent: str, child: str) -> bool:
    """parent == child ou parent est un dossier ancêtre de child (chemins relatifs normalisés)."""
    return parent == "" or child == parent or child.startswith(parent + "/")


def _now() -> str:
    from .registry import _now as now
    return now()


def _err(msg: str) -> Exception:
    from .registry import AdminError
    return AdminError(msg)


class ProjectsMixin:
    """Méthodes « projets » du Registry (load/save/terms_path sont fournis par Registry)."""

    projects_dir: Optional[Path]
    host_projects_dir: str

    # ------------------------------------------------------------------ utilitaires
    def _need_projects_dir(self) -> Path:
        if not self.projects_dir or not self.projects_dir.is_dir():
            raise _err("Dossier des projets non monté dans la console (PROJECTS_DIR)")
        return self.projects_dir.resolve()

    @staticmethod
    def _project(data: dict, pid: str) -> dict:
        p = data.get("projects", {}).get(pid)
        if p is None:
            raise _err(f"Projet {pid} introuvable")
        return p

    def project_root(self, p: dict) -> Path:
        root = self._need_projects_dir()
        d = (root / p["path"]).resolve()
        if root not in d.parents:
            raise _err("Chemin du projet hors du dossier des projets")
        return d

    def host_path(self, project_path: str, inner: str = "") -> str:
        base = PurePosixPath(self.host_projects_dir) / project_path
        return str(base / inner) if inner else str(base)

    def _resolve_in_project(self, p: dict, rel: str) -> tuple[Path, str]:
        try:
            rel = norm_rel(rel)
        except ValueError:
            raise _err("Chemin invalide") from None
        root = self.project_root(p)
        target = root / rel if rel else root
        real = target.resolve()
        if rel and real != root and root not in real.parents:  # lien symbolique sortant du projet
            raise _err("Chemin hors du projet")
        return target, rel

    @staticmethod
    def c3_source(p: dict, rel: str) -> Optional[str]:
        """Pourquoi rel est C3 : 'declared', 'inherited', 'marker' ou None."""
        for c in p.get("c3", []):
            if c == rel:
                return "declared"
            if covers(c, rel):
                return "inherited"
        if any(MARKER_NAME_RE.search(part) for part in PurePosixPath(rel).parts):
            return "marker"
        return None

    def build_c3_paths(self, data: dict) -> list[str]:
        out = []
        for p in data.get("projects", {}).values():
            out += [self.host_path(p["path"], c) for c in p.get("c3", [])]
        return sorted(set(out))

    # ------------------------------------------------------------------ lecture
    def project_candidates(self) -> list[dict]:
        """Dossiers proposés à la déclaration (profondeur 1 et 2 sous le dossier des projets)."""
        root = self._need_projects_dir()
        declared = {p["path"] for p in self.load().get("projects", {}).values()}
        out: list[dict] = []

        def walk(d: Path, depth: int) -> None:
            try:
                children = sorted(c for c in d.iterdir() if c.is_dir() and not c.name.startswith(".")
                                  and c.name not in SKIP_DIRS)
            except OSError:
                return
            for c in children:
                rel = c.relative_to(root).as_posix()
                is_git = (c / ".git").exists()
                out.append({"path": rel, "host_path": self.host_path(rel), "git": is_git,
                            "declared": rel in declared, "depth": depth})
                if depth < CANDIDATE_DEPTH and not is_git:
                    walk(c, depth + 1)
        walk(root, 1)
        return out

    def _project_view(self, pid: str, p: dict, data: dict) -> dict:
        client = data["clients"].get(p.get("client") or "")
        try:
            exists = self.project_root(p).is_dir()
        except Exception:
            exists = False
        return {"id": pid, "name": p.get("name", ""), "path": p["path"], "host_path": self.host_path(p["path"]),
                "client": p.get("client") or "", "client_name": client.get("name", "") if client else "",
                "mask_name": bool(p.get("mask_name")), "c3": list(p.get("c3", [])), "exists": exists,
                "created": p.get("created"), "updated": p.get("updated")}

    def list_projects(self) -> list[dict]:
        data = self.load()
        return [self._project_view(pid, p, data) for pid, p in sorted(data.get("projects", {}).items())]

    def get_project(self, pid: str) -> dict:
        data = self.load()
        return self._project_view(pid, self._project(data, pid), data)

    def project_tree(self, pid: str, rel: str = "") -> list[dict]:
        p = self._project(self.load(), pid)
        target, rel = self._resolve_in_project(p, rel)
        if not target.is_dir():
            raise _err("Dossier introuvable")
        try:
            items = sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError as e:
            raise _err(f"Lecture impossible : {e.strerror}") from None
        entries = []
        for it in items:
            if it.name == ".git" or it.name.endswith(":Zone.Identifier"):
                continue
            child = f"{rel}/{it.name}" if rel else it.name
            is_dir = it.is_dir() and not it.is_symlink()
            try:
                st = it.lstat()
                size, mtime = st.st_size, datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
            except OSError:
                size, mtime = 0, ""
            entries.append({
                "name": it.name, "path": child, "dir": is_dir, "size": 0 if is_dir else size, "mtime": mtime,
                "c3": self.c3_source(p, child),
                "contains_c3": is_dir and any(c.startswith(child + "/") for c in p.get("c3", [])),
            })
            if len(entries) >= MAX_TREE_ENTRIES:
                break
        return entries

    # ------------------------------------------------------------------ modifications
    @staticmethod
    def _check_client(data: dict, client: str) -> str:
        client = (client or "").strip()
        if client and client not in data["clients"]:
            raise _err(f"Client {client} non déclaré : déclarez-le d'abord dans l'écran Clients")
        return client

    def add_project(self, path: str, name: str = "", client: str = "", mask_name: bool = False) -> str:
        try:
            rel = norm_rel(path)
        except ValueError:
            raise _err("Chemin invalide") from None
        if not rel:
            raise _err("Choisissez un dossier de projet")
        data = self.load()
        projects = data.setdefault("projects", {})
        for p in projects.values():
            if p["path"] == rel:
                raise _err("Ce dossier est déjà déclaré")
            if covers(p["path"], rel) or covers(rel, p["path"]):
                raise _err(f"Ce dossier chevauche le projet déjà déclaré « {p['name']} » ({p['path']})")
        if not self.project_root({"path": rel}).is_dir():
            raise _err("Dossier introuvable")
        name = " ".join((name or PurePosixPath(rel).name).split())
        pid = base = _slug(name)
        n = 2
        while pid in projects:
            pid, n = f"{base}-{n}", n + 1
        projects[pid] = {"name": name, "path": rel, "client": self._check_client(data, client),
                         "mask_name": bool(mask_name), "c3": [], "created": _now(), "updated": _now()}
        self.save(data)
        return pid

    def update_project(self, pid: str, name: str, client: str, mask_name: bool) -> None:
        data = self.load()
        p = self._project(data, pid)
        name = " ".join((name or "").split())
        if len(name) < 2:
            raise _err("Le nom du projet est obligatoire")
        p.update(name=name, client=self._check_client(data, client), mask_name=bool(mask_name), updated=_now())
        self.save(data)

    def delete_project(self, pid: str) -> None:
        """Retire le projet de la console : ses chemins C3 ne sont plus protégés. Les fichiers restent."""
        data = self.load()
        self._project(data, pid)
        del data["projects"][pid]
        self.save(data)

    def set_c3(self, pid: str, rel: str, on: bool) -> list[str]:
        data = self.load()
        p = self._project(data, pid)
        target, rel = self._resolve_in_project(p, rel)
        if not rel:
            raise _err("Le projet entier ne peut pas être C3 : Claude ne pourrait plus y travailler. "
                       "Déclarez les dossiers ou fichiers concernés.")
        c3 = list(p.get("c3", []))
        if on:
            if not os.path.lexists(target):
                raise _err("Fichier ou dossier introuvable")
            parent = next((c for c in c3 if covers(c, rel) and c != rel), None)
            if parent:
                raise _err(f"Déjà protégé par le dossier C3 « {parent} »")
            c3 = sorted({c for c in c3 if not covers(rel, c)} | {rel})  # un dossier remplace ses descendants
        else:
            if rel not in c3:
                parent = next((c for c in c3 if covers(c, rel)), None)
                if parent:
                    raise _err(f"Protégé par le dossier C3 « {parent} » : retirez ce dossier pour libérer ce chemin")
                raise _err("Ce chemin n'est pas déclaré C3")
            c3.remove(rel)  # un chemin disparu du disque peut toujours être retiré
        p["c3"], p["updated"] = c3, _now()
        self.save(data)
        return c3

    # ------------------------------------------------------------------ analyse
    def scan_project(self, pid: str) -> dict:
        """Signale ce qui mérite une décision : termes du dictionnaire, fichiers de secrets, identifiants
        en dur. Analyse locale (rien n'est envoyé), bornée en taille ; aucune valeur n'est renvoyée."""
        p = self._project(self.load(), pid)
        root = self.project_root(p)
        if not root.is_dir():
            raise _err("Dossier du projet introuvable")
        terms = self._scan_terms()
        term_re = (re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t, _ in terms) + r")(?!\w)", re.IGNORECASE)
                   if terms else None)
        kind_of = {t.lower(): k for t, k in terms}

        found: dict[str, dict] = {}
        secret_files: list[dict] = []
        credentials: list[dict] = []
        stats = {"files": 0, "read": 0, "skipped_large": 0, "skipped_binary": 0, "truncated": False}
        total = 0
        for cur, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for fname in sorted(files):
                if stats["files"] >= SCAN_MAX_FILES or total >= SCAN_MAX_TOTAL_BYTES:
                    stats["truncated"] = True
                    break
                stats["files"] += 1
                fpath = Path(cur) / fname
                rel = fpath.relative_to(root).as_posix()
                level = self.c3_source(p, rel)
                if fname not in SECRET_FILE_EXCEPTIONS and any(fnmatch(fname, pat) for pat in SECRET_FILE_PATTERNS):
                    secret_files.append({"path": rel, "c3": level})
                    continue  # jamais lus : déjà refusés par les hooks
                try:
                    if fpath.is_symlink() or fpath.stat().st_size > SCAN_MAX_FILE_BYTES:
                        stats["skipped_large"] += 1
                        continue
                    raw = fpath.read_bytes()
                except OSError:
                    continue
                if b"\x00" in raw[:4096]:
                    stats["skipped_binary"] += 1
                    continue
                total += len(raw)
                stats["read"] += 1
                text = raw.decode("utf-8", errors="replace")
                if term_re:
                    for key in {m.group(1).lower() for m in term_re.finditer(text)}:
                        e = found.setdefault(key, {"term": key, "kind": kind_of.get(key, ""), "files": 0, "samples": []})
                        e["files"] += 1
                        if len(e["samples"]) < SCAN_MAX_SAMPLES:
                            e["samples"].append({"path": rel, "c3": level})
                if len(credentials) < SCAN_MAX_CREDENTIALS:
                    for i, line in enumerate(text.splitlines(), 1):
                        m = credential_match(line, fname)
                        if m:
                            credentials.append({"path": rel, "line": i, "key": m.group(1), "c3": level})
                            if len(credentials) >= SCAN_MAX_CREDENTIALS:
                                break
            if stats["truncated"]:
                break
        # libellé d'origine (casse du dictionnaire) plutôt que la forme minuscule
        label = {t.lower(): t for t, _ in terms}
        for e in found.values():
            e["term"] = label.get(e["term"], e["term"])
        path_terms = sorted({t for t, _ in terms
                             if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", p["path"], re.IGNORECASE)})
        return {"terms": sorted(found.values(), key=lambda e: -e["files"]),
                "secret_files": secret_files, "credentials": credentials, "path_terms": path_terms, "stats": stats}

    def _scan_terms(self) -> list[tuple[str, str]]:
        try:
            terms = json.loads(self.terms_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return []
        out = [(v, kind) for kind, values in terms.items() if isinstance(values, list) and not kind.startswith("_")
               for v in values if isinstance(v, str) and len(v) >= 3]
        return sorted(out, key=lambda x: -len(x[0]))  # le plus long d'abord dans l'alternance
