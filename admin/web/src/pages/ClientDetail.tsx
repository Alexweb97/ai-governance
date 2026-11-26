import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FileText, Lock, Plus, Save, ShieldOff, Tags } from "lucide-react";
import { api, type Client } from "../lib/api";
import { useToast } from "../lib/toast";
import { C3_DIR, useI18n } from "../i18n";
import {
  Alert, Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, TagInput, useConfirm,
} from "../components/ui";

export function Breadcrumb({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav className="flex items-center gap-1.5 text-sm text-slate-500">
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <ChevronRight className="size-3.5 text-slate-300" />}
          {it.to ? <Link to={it.to} className="hover:text-slate-900">{it.label}</Link> : <span className="text-slate-900">{it.label}</span>}
        </span>
      ))}
    </nav>
  );
}

function NewConsultationModal({ code, onClose }: { code: string; onClose: () => void }) {
  const { t } = useI18n();
  const [ref, setRef] = useState("");
  const [title, setTitle] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const m = useMutation({
    mutationFn: () => api.createConsultation(code, { ref, title }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast(t("cd.tenderCreated", { ref: r.ref }));
      navigate(`/clients/${code}/${r.ref}`);
    },
  });
  return (
    <Modal open onClose={onClose} title={t("cd.newTender")}
      description={t("cd.newTenderDesc", { c3dir: C3_DIR })}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" loading={m.isPending} disabled={!ref} onClick={() => m.mutate()}>{t("common.create")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("cd.ref")} hint={t("cd.refHint")}>
          <Input value={ref} onChange={(e) => setRef(e.target.value)} className="font-mono" placeholder="AO-2026-015" />
        </Field>
        <Field label={t("cd.tenderTitle")} hint={t("cd.tenderTitleHint")}>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("cd.tenderTitlePlaceholder")} />
        </Field>
        {m.error && <Alert>{m.error.message}</Alert>}
      </div>
    </Modal>
  );
}

function IdentityForm({ client }: { client: Client }) {
  const { t } = useI18n();
  const [name, setName] = useState(client.name);
  const [variants, setVariants] = useState(client.variants);
  useEffect(() => { setName(client.name); setVariants(client.variants); }, [client]);
  const qc = useQueryClient();
  const toast = useToast();
  const dirty = name !== client.name || variants.join("\n") !== client.variants.join("\n");
  const m = useMutation({
    mutationFn: () => client.declared
      ? api.updateClient(client.code, { name, variants })
      : api.createClient({ code: client.code, name, variants }),
    onSuccess: () => { qc.invalidateQueries(); toast(t("cd.dictUpdated")); },
  });
  return (
    <Card>
      <CardHeader icon={<Tags className="size-4" />} title={t("cd.identity")}
        description={t("cd.identityDesc")} />
      <div className="space-y-5">
        <Field label={t("clients.name")}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("clients.variants")} hint={t("cd.variantsHint")}>
          <TagInput value={variants} onChange={setVariants} placeholder={t("cd.variantPlaceholder")} />
        </Field>
        {m.error && <Alert>{m.error.message}</Alert>}
        <div className="flex justify-end">
          <Button variant="primary" icon={<Save className="size-4" />} loading={m.isPending}
            disabled={(!dirty && client.declared) || name.trim().length < 2} onClick={() => m.mutate()}>
            {client.declared ? t("common.save") : t("cd.declare")}
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function ClientDetail() {
  const { t, r } = useI18n();
  const { code = "" } = useParams();
  const { data: client, error, isLoading } = useQuery({ queryKey: ["client", code], queryFn: () => api.client(code) });
  const [newOpen, setNewOpen] = useState(false);
  const confirm = useConfirm();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const remove = useMutation({
    mutationFn: () => api.deleteClient(code),
    onSuccess: () => { qc.invalidateQueries(); toast(t("cd.removed", { code })); navigate("/clients"); },
    onError: (e) => toast(e.message, "error"),
  });

  if (isLoading) return <PageLoader />;
  if (error || !client) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader
        breadcrumb={<Breadcrumb items={[{ label: t("nav.clients"), to: "/clients" }, { label: client.code }]} />}
        title={<span className="flex items-center gap-3">{client.declared ? client.name : client.code}
          <Badge tone="brand" className="font-mono">{client.code}</Badge></span>}
        description={client.declared ? t("cd.summary", { variants: client.variants.length, tenders: client.consultations.length }) : undefined}
        actions={client.declared && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setNewOpen(true)}>{t("cd.newTender")}</Button>} />

      {!client.declared && (
        <div className="mb-6"><Alert icon={<AlertTriangle className="size-4" />} title={t("cd.notDeclared.title")}>
          {t("cd.notDeclared.body")}
        </Alert></div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
        <Card padded={false}>
          <div className="px-6 pt-6"><CardHeader icon={<FileText className="size-4" />} title={t("cd.tenders")} /></div>
          {client.consultations.length === 0 ? (
            <div className="px-6 pb-6"><EmptyState icon={<FileText className="size-5" />} title={t("cd.noTenders")}
              action={client.declared && <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setNewOpen(true)}>{t("common.create")}</Button>} /></div>
          ) : (
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {client.consultations.map((c) => (
                <li key={c.ref}>
                  <Link to={`/clients/${client.code}/${c.ref}`} className="group flex items-center gap-4 px-6 py-4 hover:bg-slate-50/70">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-slate-100 text-slate-500"><FileText className="size-4" /></div>
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-sm font-medium text-slate-900">{c.ref}</p>
                      <p className="truncate text-sm text-slate-500">{c.title || t("cd.untitled")}</p>
                    </div>
                    {c.has_confidential
                      ? <Badge tone="success" dot>{t("cd.c3Ready")}</Badge>
                      : <Badge tone="warning" dot>{t("cd.noC3", { c3dir: C3_DIR })}</Badge>}
                    <ChevronRight className="size-5 text-slate-300 group-hover:text-slate-500" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-6">
          <IdentityForm client={client} />
          {client.declared && (
            <Card className="border-rose-200/70">
              <CardHeader icon={<ShieldOff className="size-4" />} title={t("cd.removeTitle")}
                description={t("cd.removeDesc")} />
              <Button variant="danger-ghost" icon={<Lock className="size-4" />} loading={remove.isPending}
                onClick={async () => {
                  if (await confirm({ title: t("cd.removeConfirmTitle", { code: client.code }), confirmLabel: t("common.remove"),
                    message: <>{r("cd.removeConfirmMsg", { name: client.name, count: client.variants.length })}</> }))
                    remove.mutate();
                }}>{t("cd.removeBtn", { code: client.code })}</Button>
            </Card>
          )}
        </div>
      </div>
      {newOpen && <NewConsultationModal code={client.code} onClose={() => setNewOpen(false)} />}
    </>
  );
}
