import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Copy, File as FileIcon, Folder, FolderOpen, KeyRound, Lock, LockOpen,
  Radar, Save, Settings2, ShieldOff, Tags, Terminal, Trash2,
} from "lucide-react";
import { api, formatSize, type C3Source, type ProjectDetail as Project, type ScanHit, type ScanResult, type TreeEntry } from "../lib/api";
import { useToast } from "../lib/toast";
import { Alert, Badge, Button, Card, CardHeader, ErrorState, Field, Input, PageHeader, PageLoader, Switch, useConfirm } from "../components/ui";
import { Breadcrumb } from "./ClientDetail";
import { ClientSelect } from "./Projects";

const sourceLabel: Record<Exclude<C3Source, null>, string> = {
  declared: "C3 déclaré",
  inherited: "C3 (dossier parent)",
  marker: "C3 par son nom",
};

function C3Badge({ source }: { source: C3Source }) {
  if (!source) return null;
  return <Badge tone="danger"><Lock className="size-3" /> {sourceLabel[source]}</Badge>;
}

// ------------------------------------------------------------------ arborescence
function TreeLevel({ project, path, depth, onToggle, busy }:
  { project: Project; path: string; depth: number; onToggle: (e: TreeEntry) => void; busy: string | null }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["project-tree", project.id, path],
    queryFn: () => api.projectTree(project.id, path),
  });
  if (isLoading) return <p className="py-2 text-xs text-slate-400" style={{ paddingLeft: `${1 + depth * 1.25}rem` }}>Chargement…</p>;
  if (error) return <div className="p-2"><Alert>{(error as Error).message}</Alert></div>;
  if (!data?.entries.length) return <p className="py-2 text-xs text-slate-400" style={{ paddingLeft: `${1 + depth * 1.25}rem` }}>Dossier vide</p>;
  return <>{data.entries.map((e) => <TreeRow key={e.path} entry={e} project={project} depth={depth} onToggle={onToggle} busy={busy} />)}</>;
}

function TreeRow({ entry, project, depth, onToggle, busy }:
  { entry: TreeEntry; project: Project; depth: number; onToggle: (e: TreeEntry) => void; busy: string | null }) {
  const [open, setOpen] = useState(false);
  const locked = entry.c3 !== null;
  return (
    <>
      <div className={clsx("group flex items-center gap-2 border-b border-slate-50 py-1.5 pr-3 text-sm", locked ? "bg-rose-50/50" : "hover:bg-slate-50")}
        style={{ paddingLeft: `${0.75 + depth * 1.25}rem` }}>
        {entry.dir ? (
          <button type="button" onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-1.5 text-left">
            {open ? <ChevronDown className="size-3.5 shrink-0 text-slate-400" /> : <ChevronRight className="size-3.5 shrink-0 text-slate-400" />}
            {open ? <FolderOpen className={clsx("size-4 shrink-0", locked ? "text-rose-500" : "text-amber-500")} />
              : <Folder className={clsx("size-4 shrink-0", locked ? "text-rose-500" : "text-amber-500")} />}
            <span className="truncate font-mono text-[13px] text-slate-800">{entry.name}</span>
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-center gap-1.5 pl-5">
            <FileIcon className={clsx("size-4 shrink-0", locked ? "text-rose-500" : "text-slate-400")} />
            <span className="truncate font-mono text-[13px] text-slate-800">{entry.name}</span>
            <span className="shrink-0 text-xs text-slate-400">{formatSize(entry.size)}</span>
          </div>
        )}
        {entry.contains_c3 && !locked && <Badge tone="warning">contient du C3</Badge>}
        <C3Badge source={entry.c3} />
        {(entry.c3 === null || entry.c3 === "declared") && (
          <Button size="sm" variant={locked ? "ghost" : "danger-ghost"} loading={busy === entry.path}
            className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
            icon={locked ? <LockOpen className="size-3.5" /> : <Lock className="size-3.5" />} onClick={() => onToggle(entry)}>
            {locked ? "Retirer du C3" : "Passer en C3"}
          </Button>
        )}
      </div>
      {entry.dir && open && <TreeLevel project={project} path={entry.path} depth={depth + 1} onToggle={onToggle} busy={busy} />}
    </>
  );
}

// ------------------------------------------------------------------ réglages du projet
function SettingsCard({ project }: { project: Project }) {
  const [name, setName] = useState(project.name);
  const [client, setClient] = useState(project.client);
  const [maskName, setMaskName] = useState(project.mask_name);
  useEffect(() => { setName(project.name); setClient(project.client); setMaskName(project.mask_name); }, [project]);
  const dirty = name !== project.name || client !== project.client || maskName !== project.mask_name;
  const qc = useQueryClient();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.updateProject(project.id, { name, client, mask_name: maskName }),
    onSuccess: () => { qc.invalidateQueries(); toast("Projet mis à jour"); },
  });
  return (
    <Card>
      <CardHeader icon={<Settings2 className="size-4" />} title="Projet" />
      <div className="space-y-4">
        <Field label="Nom affiché"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Client" hint="Le nom du client est masqué partout dès qu'il est déclaré dans l'écran Clients.">
          <ClientSelect value={client} onChange={setClient} />
        </Field>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-900">Masquer le nom du projet</p>
            <p className="text-xs text-slate-500">Remplacé par PII_PROJET_… avant tout envoi.</p>
          </div>
          <Switch checked={maskName} onChange={setMaskName} label="Masquer le nom du projet" />
        </div>
        {m.error && <Alert>{m.error.message}</Alert>}
        <div className="flex justify-end">
          <Button variant="primary" icon={<Save className="size-4" />} loading={m.isPending} disabled={!dirty || name.trim().length < 2}
            onClick={() => m.mutate()}>Enregistrer</Button>
        </div>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ analyse
function Hit({ hit, extra }: { hit: ScanHit; extra?: string }) {
  return (
    <li className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-700" title={hit.path}>{hit.path}{extra}</span>
      {hit.c3 ? <Badge tone="success">déjà C3</Badge> : <Badge tone="warning">lisible par Claude</Badge>}
    </li>
  );
}

function ScanCard({ project }: { project: Project }) {
  const toast = useToast();
  const m = useMutation({ mutationFn: () => api.scanProject(project.id), onError: (e) => toast(e.message, "error") });
  const r: ScanResult | undefined = m.data;
  const clean = r && !r.terms.length && !r.secret_files.length && !r.credentials.length && !r.path_terms.length;
  return (
    <Card>
      <CardHeader icon={<Radar className="size-4" />} title="Analyse du projet"
        description="Recherche locale (rien n'est envoyé) : termes du dictionnaire, fichiers de secrets, identifiants écrits en dur. Aucune valeur n'est affichée."
        action={<Button size="sm" loading={m.isPending} onClick={() => m.mutate()}>{r ? "Relancer" : "Analyser"}</Button>} />
      {!r && !m.isPending && <p className="text-sm text-slate-400">Lancez l'analyse pour repérer ce qui devrait passer en C3 ou être ajouté au dictionnaire.</p>}
      {r && (
        <div className="space-y-5 text-sm">
          <p className="text-xs text-slate-500">
            {r.stats.read} fichier(s) lus sur {r.stats.files}
            {r.stats.skipped_large > 0 && ` · ${r.stats.skipped_large} trop gros`}
            {r.stats.skipped_binary > 0 && ` · ${r.stats.skipped_binary} binaires`}
            {r.stats.truncated && " · analyse partielle (projet volumineux)"}
          </p>
          {clean && <Alert tone="info" icon={<Check className="size-4" />}>Rien à signaler.</Alert>}
          {r.path_terms.length > 0 && (
            <Alert tone="warning" icon={<AlertTriangle className="size-4" />} title="Nom sensible dans le chemin du projet">
              {r.path_terms.join(", ")} apparaît dans {project.host_path}. Les chemins sont envoyés au modèle : renommez le dossier avec un code neutre.
            </Alert>
          )}
          {r.terms.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-2 font-medium text-slate-900"><Tags className="size-4 text-slate-500" /> Termes du dictionnaire trouvés</p>
              <p className="mb-2 text-xs text-slate-500">Déjà masqués avant envoi. Vérifiez qu'il n'en manque pas de variantes, et passez en C3 ce qui ne doit pas partir du tout.</p>
              {r.terms.map((t) => (
                <div key={t.term} className="mb-2 rounded-lg bg-slate-50 p-3">
                  <p className="text-[13px]"><strong>{t.term}</strong> <span className="text-slate-500">· {t.kind} · {t.files} fichier(s)</span></p>
                  <ul>{t.samples.map((h) => <Hit key={h.path} hit={h} />)}</ul>
                </div>
              ))}
            </div>
          )}
          {r.secret_files.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-2 font-medium text-slate-900"><KeyRound className="size-4 text-slate-500" /> Fichiers de secrets</p>
              <p className="mb-1 text-xs text-slate-500">Toujours refusés par les hooks (.env, clés…), même sans C3.</p>
              <ul>{r.secret_files.map((h) => <Hit key={h.path} hit={h} />)}</ul>
            </div>
          )}
          {r.credentials.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-2 font-medium text-slate-900"><KeyRound className="size-4 text-slate-500" /> Identifiants écrits en dur</p>
              <p className="mb-1 text-xs text-slate-500">Les secrets reconnus sont pseudonymisés, mais pas un mot de passe quelconque : déplacez-le dans un .env ou passez le fichier en C3.</p>
              <ul>{r.credentials.map((h) => <Hit key={`${h.path}:${h.line}`} hit={h} extra={`:${h.line} (${h.key})`} />)}</ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ page
export default function ProjectDetail() {
  const { id = "" } = useParams();
  const { data: project, error, isLoading } = useQuery({ queryKey: ["project", id], queryFn: () => api.project(id) });
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["project", id] });
    qc.invalidateQueries({ queryKey: ["project-tree", id] });
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const setC3 = async (path: string, on: boolean) => {
    if (!on && !(await confirm({ title: "Rendre ce chemin lisible par Claude ?", confirmLabel: "Retirer du C3", tone: "primary",
      message: <>« {path} » ne sera plus protégé : Claude pourra le lire, avec les données sensibles pseudonymisées.</> }))) return;
    setBusy(path);
    try { await api.setC3(id, path, on); refresh(); toast(on ? `${path} protégé (C3)` : `${path} retiré du C3`); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  };
  const remove = useMutation({
    mutationFn: () => api.deleteProject(id),
    onSuccess: () => { qc.invalidateQueries(); toast("Projet retiré de la console"); navigate("/projets"); },
    onError: (e) => toast(e.message, "error"),
  });
  const copy = async () => {
    if (!project) return;
    try { await navigator.clipboard.writeText(project.command); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { toast("Copie impossible : sélectionnez la commande à la main", "error"); }
  };

  if (isLoading) return <PageLoader />;
  if (error || !project) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader
        breadcrumb={<Breadcrumb items={[{ label: "Projets", to: "/projets" }, { label: project.name }]} />}
        title={<span className="flex items-center gap-3">{project.name}
          {project.client ? <Badge tone="brand">{project.client} · {project.client_name}</Badge> : <Badge>Interne</Badge>}</span>}
        description={<span className="font-mono">{project.host_path}</span>} />

      {!project.exists && (
        <div className="mb-6"><Alert icon={<AlertTriangle className="size-4" />} title="Dossier introuvable">
          Le projet a été déplacé ou supprimé. Ses chemins C3 restent protégés tant qu'il est déclaré.
        </Alert></div>
      )}

      <div className="mb-6 overflow-hidden rounded-2xl bg-slate-950 shadow-lg ring-1 ring-slate-900">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-300"><Terminal className="size-4" /> Travailler avec Claude Code</div>
          <span className="text-xs text-slate-500">Terminal Ubuntu (WSL)</span>
        </div>
        <div className="flex items-center gap-3 px-5 py-4">
          <code className="flex-1 overflow-x-auto font-mono text-sm whitespace-nowrap text-emerald-300"><span className="text-slate-500 select-none">$ </span>{project.command}</code>
          <Button size="sm" variant={copied ? "secondary" : "primary"} icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />} onClick={copy}>
            {copied ? "Copié" : "Copier"}
          </Button>
        </div>
        <p className="px-5 pb-4 text-xs text-slate-500">Avec Claude, les chemins C3 sont refusés, y compris via une recherche récursive (grep -r, rg) lancée sur un dossier parent.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Card padded={false}>
            <div className="px-6 pt-6">
              <CardHeader icon={<Folder className="size-4" />} title="Arborescence"
                description="Survolez une ligne pour la passer en C3. Un dossier C3 protège tout son contenu." />
            </div>
            <div className="max-h-[560px] overflow-y-auto border-t border-slate-100">
              {project.exists && <TreeLevel project={project} path="" depth={0} onToggle={(e) => setC3(e.path, e.c3 === null)} busy={busy} />}
            </div>
          </Card>
          <ScanCard project={project} />
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader icon={<Lock className="size-4" />} title="Chemins C3 déclarés"
              description="Jamais envoyés à Anthropic : lisibles uniquement avec le fournisseur de confiance." />
            {project.c3.length === 0 ? <p className="text-sm text-slate-400">Aucun. Les fichiers nommés selon la convention C3 restent protégés.</p> : (
              <ul className="divide-y divide-slate-100">
                {project.c3.map((p) => (
                  <li key={p} className="group flex items-center gap-2 py-2">
                    <Lock className="size-3.5 shrink-0 text-rose-500" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[13px]" title={p}>{p}</span>
                    <Button size="sm" variant="ghost" loading={busy === p} icon={<LockOpen className="size-3.5" />} onClick={() => setC3(p, false)} aria-label={`Retirer ${p} du C3`} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <SettingsCard project={project} />
          <Card className="border-rose-200/70">
            <CardHeader icon={<ShieldOff className="size-4" />} title="Retirer de la console"
              description="Les fichiers ne sont pas touchés, mais ses chemins C3 ne seront plus protégés." />
            <Button variant="danger-ghost" icon={<Trash2 className="size-4" />} loading={remove.isPending}
              onClick={async () => {
                if (await confirm({ title: `Retirer ${project.name} ?`, confirmLabel: "Retirer",
                  message: <>{project.c3.length > 0
                    ? <><strong>{project.c3.length} chemin(s) C3</strong> redeviendront lisibles par Claude.</>
                    : "Aucun chemin C3 déclaré."}</> }))
                  remove.mutate();
              }}>Retirer le projet</Button>
          </Card>
        </div>
      </div>
    </>
  );
}
