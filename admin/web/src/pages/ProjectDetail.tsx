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
import { useI18n } from "../i18n";
import type { Key } from "../i18n/en";
import { Alert, Badge, Button, Card, CardHeader, ErrorState, Field, Input, PageHeader, PageLoader, Switch, useConfirm } from "../components/ui";
import { Breadcrumb } from "./ClientDetail";
import { ClientSelect } from "./Projects";

const sourceLabel: Record<Exclude<C3Source, null>, Key> = {
  declared: "pd.src.declared",
  inherited: "pd.src.inherited",
  marker: "pd.src.marker",
};

function C3Badge({ source }: { source: C3Source }) {
  const { t } = useI18n();
  if (!source) return null;
  return <Badge tone="danger"><Lock className="size-3" /> {t(sourceLabel[source])}</Badge>;
}

// ------------------------------------------------------------------ arborescence
function TreeLevel({ project, path, depth, onToggle, busy }:
  { project: Project; path: string; depth: number; onToggle: (e: TreeEntry) => void; busy: string | null }) {
  const { t } = useI18n();
  const { data, error, isLoading } = useQuery({
    queryKey: ["project-tree", project.id, path],
    queryFn: () => api.projectTree(project.id, path),
  });
  if (isLoading) return <p className="py-2 text-xs text-slate-400" style={{ paddingLeft: `${1 + depth * 1.25}rem` }}>{t("common.loading")}</p>;
  if (error) return <div className="p-2"><Alert>{(error as Error).message}</Alert></div>;
  if (!data?.entries.length) return <p className="py-2 text-xs text-slate-400" style={{ paddingLeft: `${1 + depth * 1.25}rem` }}>{t("pd.emptyFolder")}</p>;
  return <>{data.entries.map((e) => <TreeRow key={e.path} entry={e} project={project} depth={depth} onToggle={onToggle} busy={busy} />)}</>;
}

function TreeRow({ entry, project, depth, onToggle, busy }:
  { entry: TreeEntry; project: Project; depth: number; onToggle: (e: TreeEntry) => void; busy: string | null }) {
  const { t } = useI18n();
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
        {entry.contains_c3 && !locked && <Badge tone="warning">{t("pd.containsC3")}</Badge>}
        <C3Badge source={entry.c3} />
        {(entry.c3 === null || entry.c3 === "declared") && (
          <Button size="sm" variant={locked ? "ghost" : "danger-ghost"} loading={busy === entry.path}
            className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
            icon={locked ? <LockOpen className="size-3.5" /> : <Lock className="size-3.5" />} onClick={() => onToggle(entry)}>
            {locked ? t("pd.removeC3") : t("pd.addC3")}
          </Button>
        )}
      </div>
      {entry.dir && open && <TreeLevel project={project} path={entry.path} depth={depth + 1} onToggle={onToggle} busy={busy} />}
    </>
  );
}

// ------------------------------------------------------------------ réglages du projet
function SettingsCard({ project }: { project: Project }) {
  const { t } = useI18n();
  const [name, setName] = useState(project.name);
  const [client, setClient] = useState(project.client);
  const [maskName, setMaskName] = useState(project.mask_name);
  useEffect(() => { setName(project.name); setClient(project.client); setMaskName(project.mask_name); }, [project]);
  const dirty = name !== project.name || client !== project.client || maskName !== project.mask_name;
  const qc = useQueryClient();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.updateProject(project.id, { name, client, mask_name: maskName }),
    onSuccess: () => { qc.invalidateQueries(); toast(t("pd.updated")); },
  });
  return (
    <Card>
      <CardHeader icon={<Settings2 className="size-4" />} title={t("pd.project")} />
      <div className="space-y-4">
        <Field label={t("proj.displayName")}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("common.client")} hint={t("pd.clientHint")}>
          <ClientSelect value={client} onChange={setClient} />
        </Field>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-900">{t("proj.maskName")}</p>
            <p className="text-xs text-slate-500">{t("pd.maskDesc")}</p>
          </div>
          <Switch checked={maskName} onChange={setMaskName} label={t("proj.maskName")} />
        </div>
        {m.error && <Alert>{m.error.message}</Alert>}
        <div className="flex justify-end">
          <Button variant="primary" icon={<Save className="size-4" />} loading={m.isPending} disabled={!dirty || name.trim().length < 2}
            onClick={() => m.mutate()}>{t("common.save")}</Button>
        </div>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ analyse
function Hit({ hit, extra }: { hit: ScanHit; extra?: string }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-700" title={hit.path}>{hit.path}{extra}</span>
      {hit.c3 ? <Badge tone="success">{t("pd.alreadyC3")}</Badge> : <Badge tone="warning">{t("pd.readable")}</Badge>}
    </li>
  );
}

function ScanCard({ project }: { project: Project }) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useMutation({ mutationFn: () => api.scanProject(project.id), onError: (e) => toast(e.message, "error") });
  const r: ScanResult | undefined = m.data;
  const clean = r && !r.terms.length && !r.secret_files.length && !r.credentials.length && !r.path_terms.length;
  return (
    <Card>
      <CardHeader icon={<Radar className="size-4" />} title={t("scan.title")}
        description={t("scan.desc")}
        action={<Button size="sm" loading={m.isPending} onClick={() => m.mutate()}>{r ? t("scan.rerun") : t("scan.run")}</Button>} />
      {!r && !m.isPending && <p className="text-sm text-slate-400">{t("scan.prompt")}</p>}
      {r && (
        <div className="space-y-5 text-sm">
          <p className="text-xs text-slate-500">
            {t("scan.stats", { read: r.stats.read, files: r.stats.files })}
            {r.stats.skipped_large > 0 && t("scan.large", { count: r.stats.skipped_large })}
            {r.stats.skipped_binary > 0 && t("scan.binary", { count: r.stats.skipped_binary })}
            {r.stats.truncated && t("scan.truncated")}
          </p>
          {clean && <Alert tone="info" icon={<Check className="size-4" />}>{t("scan.clean")}</Alert>}
          {r.path_terms.length > 0 && (
            <Alert tone="warning" icon={<AlertTriangle className="size-4" />} title={t("scan.pathTerms.title")}>
              {t("scan.pathTerms.body", { terms: r.path_terms.join(", "), path: project.host_path })}
            </Alert>
          )}
          {r.terms.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-2 font-medium text-slate-900"><Tags className="size-4 text-slate-500" /> {t("scan.terms")}</p>
              <p className="mb-2 text-xs text-slate-500">{t("scan.termsDesc")}</p>
              {r.terms.map((term) => (
                <div key={term.term} className="mb-2 rounded-lg bg-slate-50 p-3">
                  <p className="text-[13px]"><strong>{term.term}</strong> <span className="text-slate-500">· {term.kind} · {t("scan.termFiles", { count: term.files })}</span></p>
                  <ul>{term.samples.map((h) => <Hit key={h.path} hit={h} />)}</ul>
                </div>
              ))}
            </div>
          )}
          {r.secret_files.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-2 font-medium text-slate-900"><KeyRound className="size-4 text-slate-500" /> {t("scan.secretFiles")}</p>
              <p className="mb-1 text-xs text-slate-500">{t("scan.secretDesc")}</p>
              <ul>{r.secret_files.map((h) => <Hit key={h.path} hit={h} />)}</ul>
            </div>
          )}
          {r.credentials.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-2 font-medium text-slate-900"><KeyRound className="size-4 text-slate-500" /> {t("scan.creds")}</p>
              <p className="mb-1 text-xs text-slate-500">{t("scan.credsDesc")}</p>
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
  const { t, r } = useI18n();
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
    if (!on && !(await confirm({ title: t("pd.unlockTitle"), confirmLabel: t("pd.removeC3"), tone: "primary",
      message: t("pd.unlockMsg", { path }) }))) return;
    setBusy(path);
    try { await api.setC3(id, path, on); refresh(); toast(on ? t("pd.protected", { path }) : t("pd.unprotected", { path })); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  };
  const remove = useMutation({
    mutationFn: () => api.deleteProject(id),
    onSuccess: () => { qc.invalidateQueries(); toast(t("pd.removed")); navigate("/projects"); },
    onError: (e) => toast(e.message, "error"),
  });
  const copy = async () => {
    if (!project) return;
    try { await navigator.clipboard.writeText(project.command); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { toast(t("common.copyFailed"), "error"); }
  };

  if (isLoading) return <PageLoader />;
  if (error || !project) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader
        breadcrumb={<Breadcrumb items={[{ label: t("nav.projects"), to: "/projects" }, { label: project.name }]} />}
        title={<span className="flex items-center gap-3">{project.name}
          {project.client ? <Badge tone="brand">{project.client} · {project.client_name}</Badge> : <Badge>{t("common.internal")}</Badge>}</span>}
        description={<span className="font-mono">{project.host_path}</span>} />

      {!project.exists && (
        <div className="mb-6"><Alert icon={<AlertTriangle className="size-4" />} title={t("proj.missing")}>
          {t("pd.missing.body")}
        </Alert></div>
      )}

      <div className="mb-6 overflow-hidden rounded-2xl bg-slate-950 shadow-lg ring-1 ring-slate-900">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-300"><Terminal className="size-4" /> {t("common.workWithClaude")}</div>
          <span className="text-xs text-slate-500">{t("common.terminal")}</span>
        </div>
        <div className="flex items-center gap-3 px-5 py-4">
          <code className="flex-1 overflow-x-auto font-mono text-sm whitespace-nowrap text-emerald-300"><span className="text-slate-500 select-none">$ </span>{project.command}</code>
          <Button size="sm" variant={copied ? "secondary" : "primary"} icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />} onClick={copy}>
            {copied ? t("common.copied") : t("common.copy")}
          </Button>
        </div>
        <p className="px-5 pb-4 text-xs text-slate-500">{t("pd.cmdNote")}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Card padded={false}>
            <div className="px-6 pt-6">
              <CardHeader icon={<Folder className="size-4" />} title={t("pd.tree")}
                description={t("pd.treeDesc")} />
            </div>
            <div className="max-h-[560px] overflow-y-auto border-t border-slate-100">
              {project.exists && <TreeLevel project={project} path="" depth={0} onToggle={(e) => setC3(e.path, e.c3 === null)} busy={busy} />}
            </div>
          </Card>
          <ScanCard project={project} />
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader icon={<Lock className="size-4" />} title={t("pd.c3Paths")}
              description={t("pd.c3PathsDesc")} />
            {project.c3.length === 0 ? <p className="text-sm text-slate-400">{t("pd.noC3")}</p> : (
              <ul className="divide-y divide-slate-100">
                {project.c3.map((p) => (
                  <li key={p} className="group flex items-center gap-2 py-2">
                    <Lock className="size-3.5 shrink-0 text-rose-500" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[13px]" title={p}>{p}</span>
                    <Button size="sm" variant="ghost" loading={busy === p} icon={<LockOpen className="size-3.5" />} onClick={() => setC3(p, false)} aria-label={t("pd.removeAria", { path: p })} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <SettingsCard project={project} />
          <Card className="border-rose-200/70">
            <CardHeader icon={<ShieldOff className="size-4" />} title={t("pd.removeTitle")}
              description={t("pd.removeDesc")} />
            <Button variant="danger-ghost" icon={<Trash2 className="size-4" />} loading={remove.isPending}
              onClick={async () => {
                if (await confirm({ title: t("pd.removeConfirmTitle", { name: project.name }), confirmLabel: t("common.remove"),
                  message: <>{project.c3.length > 0
                    ? r("pd.removeConfirmC3", { count: project.c3.length })
                    : t("pd.removeConfirmNone")}</> }))
                  remove.mutate();
              }}>{t("pd.removeBtn")}</Button>
          </Card>
        </div>
      </div>
    </>
  );
}
