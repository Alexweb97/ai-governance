"""
Logique de la console d'administration (sans dépendance web, testable seule).

Deux emplacements :
  - config_dir  (~/.config/claude-governance) : clients.json (registre), terms.json (dictionnaire
    lu par le proxy et les hooks, régénéré à chaque modification), overrides.json (réglages) ;
  - clients_dir (~/clients) : une arborescence par client et par consultation :

        <CODE>/<REF>/travail/DCE                  niveau C2 : pseudonymisé
        <CODE>/<REF>/travail/memoire-technique    niveau C2
        <CODE>/<REF>/_confidentiel                niveau C3 : jamais lu par Claude
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Optional

from .projects import ProjectsMixin
from .settings import SettingsMixin

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONFIDENTIAL_DIR = "_confidentiel"
SUBDIRS = ("travail/DCE", "travail/memoire-technique", CONFIDENTIAL_DIR)
# Destinations proposées dans la console -> dossier relatif à la consultation
DESTINATIONS = {
    "dce": "travail/DCE",
    "memoire": "travail/memoire-technique",
    "travail": "travail",
    "confidentiel": CONFIDENTIAL_DIR,
}
def _trusted_info() -> dict:
    """Fournisseur de confiance décrit par les variables TRUSTED_* (sans la clé, jamais transmise ici)."""
    from urllib.parse import urlparse
    name = os.environ.get("TRUSTED_NAME", "") or "Fournisseur de confiance"
    model = os.environ.get("TRUSTED_MODEL", "")
    host = urlparse(os.environ.get("TRUSTED_URL", "")).hostname or ""
    detail = " · ".join(x for x in (f"modèle {model}" if model else "", host) if x) or "Non configuré (TRUSTED_URL, TRUSTED_MODEL)"
    # model/host/custom_name : champs bruts pour que la console compose le texte dans la langue choisie
    return {"name": name, "vendor": "Votre infrastructure", "detail": detail,
            "hosting": "Fournisseur choisi par vous · seul autorisé sur le C3",
            "model": model, "host": host, "custom_name": bool(os.environ.get("TRUSTED_NAME"))}


PROVIDERS = {
    "claude": {"name": "Claude", "vendor": "Anthropic", "detail": "Abonnement Claude · modèles Claude",
               "hosting": "Hébergé par Anthropic"},
    "trusted": _trusted_info(),
}
MAX_LIST_FILES = 2000
C3_IDLE_HOURS = 12  # une session C3 sans activité depuis plus longtemps est considérée fermée


class AdminError(ValueError):
    """Erreur de saisie, affichée telle quelle à l'utilisateur."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, data) -> None:
    """Écriture atomique : le proxy et les hooks ne lisent jamais un fichier à moitié écrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _clean_terms(values) -> list[str]:
    out, seen = [], set()
    for v in values or []:
        v = " ".join(str(v).split())
        if len(v) >= 2 and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def safe_filename(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f:]", "_", name)
    if not name or name in (".", ".."):
        raise AdminError("Nom de fichier invalide")
    return name[:200]


class Registry(ProjectsMixin, SettingsMixin):
    def __init__(self, config_dir: Path, clients_dir: Path, projects_dir: Optional[Path] = None,
                 host_projects_dir: Optional[str] = None, policy_path: Optional[Path] = None):
        # policy.json : valeurs par défaut des réglages (lecture seule)
        self.policy_path = Path(policy_path) if policy_path else None
        self.config_dir = Path(config_dir)
        self.clients_dir = Path(clients_dir)
        # projets de code : dossier monté dans la console, et le même dossier vu de l'hôte (hooks)
        self.projects_dir = Path(projects_dir) if projects_dir else None
        self.host_projects_dir = str(host_projects_dir or projects_dir or "")
        self.c3_paths_path = self.config_dir / "c3-paths.json"
        self.registry_path = self.config_dir / "clients.json"
        self.terms_path = self.config_dir / "terms.json"
        self.overrides_path = self.config_dir / "overrides.json"

    # ------------------------------------------------------------------ registre
    def load(self) -> dict:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"extra_terms": self._legacy_terms()}
        data.setdefault("clients", {})
        data.setdefault("extra_terms", {})
        data.setdefault("projects", {})
        return data

    def _legacy_terms(self) -> dict:
        """Premier lancement : reprend un terms.json saisi à la main pour ne rien perdre."""
        try:
            terms = json.loads(self.terms_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return {k: v for k, v in terms.items() if isinstance(v, list) and not k.startswith("_")}

    def save(self, data: dict) -> None:
        atomic_write_json(self.registry_path, data)
        atomic_write_json(self.terms_path, self.build_terms(data))
        atomic_write_json(self.c3_paths_path, {
            "_comment": "Généré par la console (Projets). Chemins C3 déclarés, absolus côté hôte : "
                        "lus par les hooks et le proxy en plus du marqueur de policy.json.",
            "paths": self.build_c3_paths(data)})

    @staticmethod
    def build_terms(data: dict) -> dict:
        """Dictionnaire lu par le proxy et les hooks : {TYPE: [termes]}."""
        clients, projects = [], []
        for c in data.get("clients", {}).values():
            clients += [c.get("name", "")] + list(c.get("variants", []))
            for cons in c.get("consultations", {}).values():
                projects.append(cons.get("title", ""))
        projects += [p.get("name", "") for p in data.get("projects", {}).values() if p.get("mask_name")]
        terms = {"_comment": "Généré par la console d'administration. Ne pas modifier à la main.",
                 "CLIENT": _clean_terms(clients), "PROJET": _clean_terms(projects)}
        for type_, values in data.get("extra_terms", {}).items():
            key = re.sub(r"[^A-Z0-9_]", "_", str(type_).upper()).strip("_")
            if key and not key.startswith("_"):
                terms[key] = _clean_terms(terms.get(key, []) + list(values))
        return {k: v for k, v in terms.items() if k == "_comment" or v}

    # ------------------------------------------------------------------ clients
    def _check_code(self, code: str) -> str:
        code = (code or "").strip()
        if not CODE_RE.fullmatch(code):
            raise AdminError("Code client invalide : lettres, chiffres, - et _ uniquement (ex. C001)")
        return code

    def next_code(self) -> str:
        used = set(self.load()["clients"]) | {p.name for p in self._client_dirs()}
        n = 1
        while f"C{n:03d}" in used:
            n += 1
        return f"C{n:03d}"

    def _client_dirs(self) -> list[Path]:
        if not self.clients_dir.is_dir():
            return []
        return sorted(p for p in self.clients_dir.iterdir() if p.is_dir() and not p.name.startswith("."))

    def list_clients(self) -> list[dict]:
        data = self.load()
        out = []
        for code, c in sorted(data["clients"].items()):
            out.append({**c, "code": code, "declared": True,
                        "consultations": self.list_consultations(code, data)})
        for d in self._client_dirs():
            if d.name not in data["clients"]:
                out.append({"code": d.name, "name": "", "variants": [], "declared": False,
                            "consultations": self.list_consultations(d.name, data)})
        return out

    def get_client(self, code: str) -> dict:
        code = self._check_code(code)
        data = self.load()
        c = data["clients"].get(code)
        if c is None:
            if not (self.clients_dir / code).is_dir():
                raise AdminError(f"Client {code} introuvable")
            c = {"name": "", "variants": []}
        return {**c, "code": code, "declared": code in data["clients"],
                "consultations": self.list_consultations(code, data)}

    def save_client(self, code: str, name: str, variants, create: bool) -> str:
        code = self._check_code(code)
        name = " ".join((name or "").split())
        if len(name) < 2:
            raise AdminError("Le nom du client est obligatoire")
        if isinstance(variants, str):
            variants = variants.splitlines()
        data = self.load()
        if create and code in data["clients"]:
            raise AdminError(f"Le code {code} est déjà utilisé")
        entry = data["clients"].setdefault(code, {"created": _now(), "consultations": {}})
        entry["name"] = name
        entry["variants"] = [v for v in _clean_terms(variants) if v.lower() != name.lower()]
        entry["updated"] = _now()
        self.save(data)
        (self.clients_dir / code).mkdir(parents=True, exist_ok=True)
        return code

    def delete_client(self, code: str) -> None:
        """Retire le client du dictionnaire. Les dossiers et fichiers sont conservés."""
        code = self._check_code(code)
        data = self.load()
        used = [p["name"] for p in data["projects"].values() if p.get("client") == code]
        if used:
            raise AdminError(f"Client associé aux projets {', '.join(used)} : changez d'abord leur client")
        if data["clients"].pop(code, None) is None:
            raise AdminError(f"Client {code} non déclaré")
        self.save(data)

    # ------------------------------------------------------------------ consultations
    def _check_ref(self, ref: str) -> str:
        ref = (ref or "").strip()
        if not REF_RE.fullmatch(ref):
            raise AdminError("Référence invalide : lettres, chiffres, '.', '-' et '_' uniquement "
                             "(ex. AO-2026-015). Évitez d'y mettre le nom du client.")
        return ref

    def list_consultations(self, code: str, data: Optional[dict] = None) -> list[dict]:
        data = data or self.load()
        meta = data["clients"].get(code, {}).get("consultations", {})
        base = self.clients_dir / code
        refs = sorted({p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")}
                      if base.is_dir() else set())
        return [{"ref": r, "title": meta.get(r, {}).get("title", ""),
                 "has_confidential": (base / r / CONFIDENTIAL_DIR).is_dir()} for r in refs]

    def add_consultation(self, code: str, ref: str, title: str = "") -> str:
        code, ref = self._check_code(code), self._check_ref(ref)
        data = self.load()
        if code not in data["clients"]:
            raise AdminError("Déclarez d'abord le client (nom et variantes) avant de créer une consultation")
        cdir = self.clients_dir / code / ref
        if cdir.exists():
            raise AdminError(f"La consultation {ref} existe déjà")
        for sub in SUBDIRS:
            (cdir / sub).mkdir(parents=True, exist_ok=True)
        title = " ".join((title or "").split())
        data["clients"][code].setdefault("consultations", {})[ref] = {"title": title, "created": _now()}
        self.save(data)
        return ref

    def update_consultation(self, code: str, ref: str, title: str) -> None:
        code, ref = self._check_code(code), self._check_ref(ref)
        data = self.load()
        if code not in data["clients"]:
            raise AdminError("Client non déclaré")
        self.consultation_dir(code, ref)
        cons = data["clients"][code].setdefault("consultations", {}).setdefault(ref, {"created": _now()})
        cons["title"] = " ".join((title or "").split())
        self.save(data)

    def consultation_dir(self, code: str, ref: str) -> Path:
        d = self.clients_dir / self._check_code(code) / self._check_ref(ref)
        if not d.is_dir():
            raise AdminError(f"Consultation {code}/{ref} introuvable")
        return d

    def ensure_structure(self, code: str, ref: str) -> None:
        d = self.consultation_dir(code, ref)
        for sub in SUBDIRS:
            (d / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ fichiers
    def _resolve_inside(self, base: Path, rel: str) -> Path:
        p = (base / rel).resolve()
        try:
            p.relative_to(base.resolve())
        except ValueError:
            raise AdminError("Chemin invalide") from None
        return p

    @staticmethod
    def level_of(rel: str) -> str:
        parts = Path(rel).parts
        return "C3" if any(x == CONFIDENTIAL_DIR or ".confidentiel." in x for x in parts) else "C2"

    def list_files(self, code: str, ref: str) -> list[dict]:
        base = self.consultation_dir(code, ref)
        out = []
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if name.startswith(".") or name.endswith(":Zone.Identifier"):
                    continue
                p = Path(root) / name
                rel = p.relative_to(base).as_posix()
                st = p.stat()
                out.append({"path": rel, "name": name, "folder": str(Path(rel).parent),
                            "level": self.level_of(rel), "size": st.st_size,
                            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")})
                if len(out) >= MAX_LIST_FILES:
                    return out
        return out

    def _unique(self, target: Path) -> Path:
        if not target.exists():
            return target
        stem, suffix = target.stem, target.suffix
        for i in range(1, 1000):
            cand = target.with_name(f"{stem} ({i}){suffix}")
            if not cand.exists():
                return cand
        raise AdminError("Trop de fichiers portant ce nom")

    def _destination(self, base: Path, dest: str) -> Path:
        if dest not in DESTINATIONS:
            raise AdminError("Destination inconnue")
        d = base / DESTINATIONS[dest]
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_upload(self, code: str, ref: str, dest: str, filename: str, stream: BinaryIO) -> str:
        base = self.consultation_dir(code, ref)
        target = self._unique(self._destination(base, dest) / safe_filename(filename))
        with open(target, "wb") as f:
            shutil.copyfileobj(stream, f, length=1024 * 1024)
        return target.relative_to(base).as_posix()

    def move_file(self, code: str, ref: str, rel: str, dest: str) -> str:
        base = self.consultation_dir(code, ref)
        src = self._resolve_inside(base, rel)
        if not src.is_file():
            raise AdminError("Fichier introuvable")
        target = self._unique(self._destination(base, dest) / src.name)
        src.rename(target)
        return target.relative_to(base).as_posix()

    def delete_file(self, code: str, ref: str, rel: str) -> None:
        base = self.consultation_dir(code, ref)
        p = self._resolve_inside(base, rel)
        if not p.is_file():
            raise AdminError("Fichier introuvable")
        p.unlink()

    # ------------------------------------------------------------------ fournisseur de modèle
    def get_provider(self) -> str:
        p = self._overrides().get("provider", "claude")
        return p if p in PROVIDERS else "claude"

    def set_provider(self, provider: str) -> str:
        if provider not in PROVIDERS:
            raise AdminError("Fournisseur inconnu")
        if provider != "trusted":
            open_ = [s for s in self.c3_sessions() if s["open"]]
            if open_:
                raise AdminError(
                    f"{len(open_)} session(s) C3 encore ouverte(s) : fermez-les dans Claude Code (/exit) ou "
                    "clôturez-les ici avant de revenir à Claude. Elles ne pourront jamais être reprises avec Claude.")
        # Le nom affiché est recopié pour les hooks (ligne d'état, message de session), qui ne lisent pas l'env.
        atomic_write_json(self.overrides_path, {**self._overrides(), "provider": provider,
                                                "provider_label": PROVIDERS[provider]["name"]})
        return provider

    # ------------------------------------------------------------------ sessions C3
    @property
    def c3_path(self) -> Path:
        return self.config_dir / "c3-sessions.json"

    def c3_sessions(self) -> list[dict]:
        """Sessions ayant lu du contenu C3 (écrites par les hooks). "open" : ni terminée ni inactive."""
        try:
            data = json.loads(self.c3_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        limit = datetime.now(timezone.utc) - timedelta(hours=C3_IDLE_HOURS)
        out = []
        for sid, s in data.items():
            try:
                recent = datetime.fromisoformat(s.get("last") or s.get("opened")) > limit
            except (TypeError, ValueError):
                recent = True
            out.append({"id": sid, "short": sid[:8], "cwd": s.get("cwd", ""), "opened": s.get("opened"),
                        "last": s.get("last"), "ended": s.get("ended"), "accesses": s.get("accesses", 0),
                        "open": not s.get("ended") and recent})
        return sorted(out, key=lambda x: x.get("last") or "", reverse=True)

    def close_c3_session(self, session_id: str) -> None:
        """Clôture manuelle (session interrompue sans SessionEnd). Elle reste bloquée vers Anthropic."""
        import fcntl
        with open(self.config_dir / ".c3.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = json.loads(self.c3_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = {}
            if session_id not in data:
                raise AdminError("Session C3 inconnue")
            data[session_id]["ended"] = _now()
            atomic_write_json(self.c3_path, data)
