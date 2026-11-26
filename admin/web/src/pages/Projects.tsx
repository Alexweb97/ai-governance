import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FolderGit2, GitBranch, Lock, Plus, Search } from "lucide-react";
import clsx from "clsx";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { useI18n } from "../i18n";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Switch } from "../components/ui";

export function ClientSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useI18n();
  const { data } = useQuery({ queryKey: ["clients"], queryFn: api.clients });
  const declared = (data?.clients ?? []).filter((c) => c.declared);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="block h-9 w-full rounded-lg border-0 bg-white px-3 text-sm text-slate-900 shadow-xs ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-brand-500 focus:outline-none">
      <option value="">{t("proj.internalOption")}</option>
      {declared.map((c) => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}
    </select>
  );
}

function NewProjectModal({ onClose }: { onClose: () => void }) {
  const { t, r } = useI18n();
  const { data, error, isLoading } = useQuery({ queryKey: ["project-candidates"], queryFn: api.projectCandidates });
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [maskName, setMaskName] = useState(false);
  const [q, setQ] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const m = useMutation({
    mutationFn: () => api.createProject({ path, name, client, mask_name: maskName }),
    onSuccess: (res) => {
      qc.invalidateQueries();
      toast(t("proj.declared"));
      navigate(`/projects/${res.id}`);
    },
  });
  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data?.candidates ?? []).filter((c) => !s || c.path.toLowerCase().includes(s));
  }, [data, q]);

  return (
    <Modal open onClose={onClose} size="lg" title={t("proj.newTitle")}
      description={<>{r("proj.newDesc", { root: data?.root ?? "~/project" }, "font-mono")}</>}
      footer={<>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" loading={m.isPending} disabled={!path} onClick={() => m.mutate()}>{t("proj.register")}</Button>
      </>}>
      <div className="space-y-5">
        <div>
          <div className="relative mb-2">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("proj.filter")} className="pl-9" />
          </div>
          <div className="max-h-64 overflow-y-auto rounded-lg ring-1 ring-slate-200">
            {isLoading && <p className="p-4 text-sm text-slate-400">{t("common.loading")}</p>}
            {error && <div className="p-3"><Alert>{(error as Error).message}</Alert></div>}
            {list.map((c) => (
              <button key={c.path} type="button" disabled={c.declared}
                onClick={() => { setPath(c.path); if (!name || name === path.split("/").pop()) setName(c.path.split("/").pop() ?? ""); }}
                className={clsx("flex w-full items-center gap-2 border-b border-slate-100 px-3 py-2 text-left text-sm last:border-0",
                  c.declared ? "cursor-not-allowed text-slate-400" : path === c.path ? "bg-brand-50 text-brand-700" : "hover:bg-slate-50")}
                style={{ paddingLeft: `${0.75 + (c.depth - 1) * 1.25}rem` }}>
                {c.git ? <GitBranch className="size-4 shrink-0 text-slate-400" /> : <FolderGit2 className="size-4 shrink-0 text-slate-300" />}
                <span className="flex-1 truncate font-mono">{c.path.split("/").pop()}</span>
                {c.declared && <Badge>{t("proj.alreadyDeclared")}</Badge>}
                {c.git && !c.declared && <Badge tone="brand">git</Badge>}
              </button>
            ))}
            {data && list.length === 0 && <p className="p-4 text-sm text-slate-400">{t("proj.noFolders")}</p>}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("proj.displayName")}><Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("proj.namePlaceholder")} /></Field>
          <Field label={t("common.client")}><ClientSelect value={client} onChange={setClient} /></Field>
        </div>
        <div className="flex items-start justify-between gap-4 rounded-lg bg-slate-50 p-3">
          <div>
            <p className="text-sm font-medium text-slate-900">{t("proj.maskName")}</p>
            <p className="text-xs text-slate-500">{t("proj.maskNameDesc")}</p>
          </div>
          <Switch checked={maskName} onChange={setMaskName} label={t("proj.maskName")} />
        </div>
        {m.error && <Alert>{m.error.message}</Alert>}
      </div>
    </Modal>
  );
}

export default function Projects() {
  const { t } = useI18n();
  const { data, error, isLoading } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [open, setOpen] = useState(false);
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader title={t("proj.title")}
        description={t("proj.description")}
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)} disabled={!data.mounted}>{t("proj.registerBtn")}</Button>} />

      {!data.mounted && (
        <div className="mb-6"><Alert icon={<AlertTriangle className="size-4" />} title={t("proj.notMounted.title")}>
          {t("proj.notMounted.body", { root: data.root })}
        </Alert></div>
      )}

      <Card padded={false}>
        {data.projects.length === 0 ? (
          <div className="p-6"><EmptyState icon={<FolderGit2 className="size-5" />} title={t("proj.none")}
            description={t("proj.noneDesc")}
            action={data.mounted && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>{t("proj.registerBtn")}</Button>} /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <th className="px-6 py-3 font-medium">{t("proj.col.project")}</th>
                <th className="px-3 py-3 font-medium">{t("common.client")}</th>
                <th className="px-3 py-3 font-medium">{t("proj.col.c3")}</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.projects.map((p) => (
                <tr key={p.id} className="group hover:bg-slate-50/70">
                  <td className="px-6 py-4">
                    <Link to={`/projects/${p.id}`} className="flex items-center gap-3">
                      <div className="flex size-9 items-center justify-center rounded-lg bg-brand-50 text-brand-700 ring-1 ring-brand-100"><FolderGit2 className="size-4" /></div>
                      <div className="min-w-0">
                        <p className="font-medium text-slate-900">{p.name} {!p.exists && <Badge tone="danger" dot>{t("proj.missing")}</Badge>}</p>
                        <p className="truncate font-mono text-xs text-slate-500">{p.host_path}</p>
                      </div>
                    </Link>
                  </td>
                  <td className="px-3 py-4">{p.client ? <Badge tone="brand">{p.client} · {p.client_name}</Badge> : <Badge>{t("common.internal")}</Badge>}</td>
                  <td className="px-3 py-4">
                    {p.c3.length ? <Badge tone="danger"><Lock className="size-3" /> {p.c3.length}</Badge> : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Link to={`/projects/${p.id}`} className="inline-flex text-slate-300 group-hover:text-slate-500"><ChevronRight className="size-5" /></Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {open && <NewProjectModal onClose={() => setOpen(false)} />}
    </>
  );
}
