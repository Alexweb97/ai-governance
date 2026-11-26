import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle, Banknote, BrainCircuit, Building2, Check, Cloud, Cpu, EyeOff, Gauge, Globe, History as History_, Image, Info, ListX, Lock,
  MessageCircleQuestion, RotateCcw, Save,
} from "lucide-react";
import { api, formatDate, type BoolSettingKey, type Decision, type ProviderId, type Settings as S, type SettingsResponse } from "../lib/api";
import { useToast } from "../lib/toast";
import { Alert, Badge, Button, Card, CardHeader, ErrorState, PageHeader, PageLoader, Switch, TagInput, useConfirm } from "../components/ui";
import { describeProvider } from "../lib/provider";
import { C3_DIR, useI18n } from "../i18n";
import { settingLabelsEn, type Key } from "../i18n/en";

function C3Sessions() {
  const { t, r } = useI18n();
  const { data } = useQuery({ queryKey: ["c3"], queryFn: api.c3Sessions, refetchInterval: 10000 });
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const sessions = data?.sessions ?? [];
  if (!sessions.length) return null;
  const open = sessions.filter((s) => s.open);
  const close = async (id: string, short: string) => {
    if (!(await confirm({ title: t("set.c3.closeTitle", { short }), confirmLabel: t("set.c3.closeConfirm"), tone: "primary",
      message: <>{r("set.c3.closeMsg")}</> }))) return;
    try { await api.closeC3Session(id); qc.invalidateQueries(); toast(t("set.c3.closed")); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="mt-6 rounded-xl ring-1 ring-violet-200 bg-violet-50/40">
      <div className="flex items-start gap-3 px-5 pt-4">
        <Lock className="mt-0.5 size-4 text-violet-600" />
        <div>
          <p className="text-sm font-semibold text-slate-900">{t("set.c3.title")} {open.length > 0 && <Badge tone="danger" className="ml-1">{t("set.c3.open", { count: open.length })}</Badge>}</p>
          <p className="mt-0.5 text-sm text-slate-600">
            {r("set.c3.desc")}
            {open.length > 0 && t("set.c3.blocked")}
          </p>
        </div>
      </div>
      <ul className="mt-3 divide-y divide-violet-100 border-t border-violet-100">
        {sessions.slice(0, 8).map((s) => (
          <li key={s.id} className="flex items-center gap-4 px-5 py-2.5 text-sm">
            <code className="font-mono text-xs text-slate-700">{s.short}</code>
            <span className="min-w-0 flex-1 truncate text-slate-500" title={s.cwd}>{s.cwd}</span>
            <span className="text-xs text-slate-400 tabular-nums">{t("set.c3.accesses", { count: s.accesses, date: formatDate(s.last) })}</span>
            {s.open ? <><Badge tone="danger" dot>{t("set.c3.openBadge")}</Badge><Button size="sm" variant="ghost" onClick={() => close(s.id, s.short)}>{t("set.c3.closeConfirm")}</Button></>
              : <Badge dot>{t("set.c3.closedBadge")}</Badge>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ProviderCard() {
  const { t, r } = useI18n();
  const { data } = useQuery({ queryKey: ["provider"], queryFn: api.provider });
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const m = useMutation({
    mutationFn: (p: ProviderId) => api.setProvider(p),
    onSuccess: (res) => {
      qc.invalidateQueries();
      toast(t("set.prov.switched", { name: data ? describeProvider(res.provider, data.providers[res.provider], t).name : res.provider }));
    },
    onError: (e) => toast(e.message, "error"),
  });
  if (!data) return null;
  const choose = async (p: ProviderId) => {
    if (p === data.provider) return;
    const info = describeProvider(p, data.providers[p], t);
    if (await confirm({
      title: t("set.prov.switchTitle", { name: info.name }), confirmLabel: t("set.prov.use", { name: info.name }), tone: "primary",
      message: <div className="space-y-2">
        <p>{r("set.prov.msg1", { name: info.name, detail: info.detail })}</p>
        <p>{r("set.prov.msg2")}</p>
        <p>{p === "trusted" ? r("set.prov.toTrusted") : r("set.prov.toClaude")}</p>
      </div>,
    })) m.mutate(p);
  };
  return (
    <Card className="mb-6">
      <CardHeader icon={<Cpu className="size-4" />} title={t("set.prov.title")}
        description={t("set.prov.desc")} />
      <div className="grid gap-4 md:grid-cols-2">
        {(Object.keys(data.providers) as ProviderId[]).map((p) => {
          const info = describeProvider(p, data.providers[p], t);
          const active = data.provider === p;
          const Icon = p === "trusted" ? Building2 : Cloud;
          return (
            <button key={p} type="button" onClick={() => choose(p)} disabled={m.isPending}
              className={clsx("relative rounded-xl p-5 text-left ring-1 transition-all",
                active ? "bg-brand-50/60 ring-2 ring-brand-500" : "bg-white ring-slate-200 hover:ring-slate-300 hover:shadow-sm")}>
              {active && <span className="absolute top-4 right-4 flex size-6 items-center justify-center rounded-full bg-brand-600 text-white"><Check className="size-3.5" /></span>}
              <div className={clsx("mb-3 inline-flex rounded-lg p-2", active ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600")}><Icon className="size-5" /></div>
              <p className="text-base font-semibold text-slate-900">{info.name} <span className="font-normal text-slate-500">· {info.vendor}</span></p>
              <p className="mt-1 text-sm text-slate-600">{info.detail}</p>
              <p className="mt-3 text-xs text-slate-500">{info.hosting}</p>
            </button>
          );
        })}
      </div>
      <div className="mt-4">
        <Alert tone="info" icon={<Info className="size-4" />}>
          {r("set.prov.info", { c3dir: C3_DIR })}
        </Alert>
      </div>
      <C3Sessions />
    </Card>
  );
}


// ------------------------------------------------------------------ réglages de gouvernance
type Data = SettingsResponse;
const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** La modification affaiblit-elle la protection ? (même règle que le serveur, pour demander confirmation) */
function reduces(patch: Partial<S>, cur: S): Key[] {
  const out: Key[] = [];
  for (const k of ["mask_amounts", "ner_documents", "ner_tool_results"] as const)
    if (k in patch && cur[k] && patch[k] === false) out.push("red.detection");
  if (patch.allow_images && !cur.allow_images) out.push("red.images");
  if (patch.ner_threshold !== undefined && patch.ner_threshold > cur.ner_threshold) out.push("red.threshold");
  if (patch.mask_types && Object.entries(patch.mask_types).some(([t, v]) => cur.mask_types[t] && !v)) out.push("red.type");
  if (patch.decisions && Object.entries(patch.decisions).some(([d, v]) => cur.decisions[d] === "deny" && v === "ask")) out.push("red.decision");
  if (patch.allowlist_extra && patch.allowlist_extra.some((v) => !cur.allowlist_extra.includes(v))) out.push("red.allowlist");
  if (patch.pii_tables && cur.pii_tables.some((v) => !patch.pii_tables!.includes(v))) out.push("red.tables");
  if (patch.web_deny_domains_extra && cur.web_deny_domains_extra.some((v) => !patch.web_deny_domains_extra!.includes(v))) out.push("red.domains");
  return [...new Set(out)];
}

function useSave(data: Data) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const m = useMutation({
    mutationFn: (patch: Partial<S>) => api.updateSettings(patch),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["status"] }); toast(t("set.saved")); },
    onError: (e) => toast(e.message, "error"),
  });
  const save = async (patch: Partial<S>) => {
    const why = reduces(patch, data.settings);
    if (why.length && !(await confirm({
      title: t("set.reduce.title"), confirmLabel: t("common.confirm"), tone: "danger",
      message: <div className="space-y-2"><p>{t("set.reduce.msg1", { reasons: why.map((k) => t(k)).join(" ; ") })}</p>
        <p>{t("set.reduce.msg2")}</p></div>,
    }))) return false;
    await m.mutateAsync(patch).catch(() => {});
    return true;
  };
  return { save, pending: m.isPending };
}

function Row({ icon, title, help, children, changed }:
  { icon?: React.ReactNode; title: string; help?: React.ReactNode; children: React.ReactNode; changed?: boolean }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center justify-between gap-6 px-6 py-4">
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 rounded-lg bg-slate-100 p-2 text-slate-600">{icon}</div>}
        <div>
          <p className="text-sm font-medium text-slate-900">{title} {changed && <Badge tone="warning" className="ml-1">{t("common.modified")}</Badge>}</p>
          {help && <p className="mt-0.5 max-w-2xl text-sm text-slate-500">{help}</p>}
        </div>
      </div>
      <div className="shrink-0">{children}</div>
    </li>
  );
}

function Section({ icon, title, description, children }: { icon: React.ReactNode; title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card padded={false} className="mb-6">
      <div className="px-6 pt-6"><CardHeader icon={icon} title={title} description={description} /></div>
      <ul className="divide-y divide-slate-100 border-t border-slate-100">{children}</ul>
    </Card>
  );
}

function ListEditor({ value, onSave, placeholder, pending, defaults }:
  { value: string[]; onSave: (v: string[]) => Promise<boolean>; placeholder: string; pending: boolean; defaults?: string[] }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const dirty = !sameList(draft, value);
  return (
    <div className="space-y-2">
      <TagInput value={draft} onChange={setDraft} placeholder={placeholder} />
      <div className="flex justify-end gap-2">
        {defaults && !sameList(draft, defaults) && <Button size="sm" variant="ghost" onClick={() => setDraft(defaults)}>{t("common.defaults")}</Button>}
        {dirty && <Button size="sm" variant="ghost" onClick={() => setDraft(value)}>{t("common.cancel")}</Button>}
        <Button size="sm" variant="primary" icon={<Save className="size-3.5" />} disabled={!dirty} loading={pending}
          onClick={async () => { if (!(await onSave(draft))) setDraft(value); }}>{t("common.save")}</Button>
      </div>
    </div>
  );
}

function Segmented({ value, onChange, disabled }: { value: Decision; onChange: (v: Decision) => void; disabled?: boolean }) {
  const { t } = useI18n();
  const opts: { v: Decision; label: string }[] = [{ v: "ask", label: t("set.ask") }, { v: "deny", label: t("set.deny") }];
  return (
    <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
      {opts.map((o) => (
        <button key={o.v} type="button" disabled={disabled} onClick={() => o.v !== value && onChange(o.v)}
          className={clsx("rounded-md px-3 py-1 text-[13px] font-medium transition-colors",
            value === o.v ? (o.v === "deny" ? "bg-rose-600 text-white shadow-sm" : "bg-white text-slate-900 shadow-sm") : "text-slate-500 hover:text-slate-800")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ThresholdRow({ data, save, pending }: { data: Data; save: (p: Partial<S>) => Promise<boolean>; pending: boolean }) {
  const { t } = useI18n();
  const cur = data.settings.ner_threshold;
  const [v, setV] = useState(cur);
  useEffect(() => setV(cur), [cur]);
  return (
    <Row icon={<Gauge className="size-4" />} title={t("set.threshold.title")} changed={cur !== data.defaults.ner_threshold}
      help={t("set.threshold.help", { value: data.defaults.ner_threshold.toFixed(2) })}>
      <div className="flex items-center gap-3">
        <input type="range" min={0.5} max={0.95} step={0.05} value={v} onChange={(e) => setV(Number(e.target.value))}
          className="w-36 accent-brand-600" aria-label={t("set.threshold.title")} />
        <span className="w-10 text-right font-mono text-sm tabular-nums">{v.toFixed(2)}</span>
        <Button size="sm" variant="primary" disabled={v === cur} loading={pending}
          onClick={async () => { if (!(await save({ ner_threshold: v }))) setV(cur); }}>{t("set.apply")}</Button>
      </div>
    </Row>
  );
}

function fmt(v: unknown, t: ReturnType<typeof useI18n>["t"]): string {
  if (typeof v === "boolean") return v ? t("fmt.yes") : t("fmt.no");
  if (Array.isArray(v)) return t("fmt.entries", { count: v.length });
  if (v === "ask") return t("fmt.ask");
  if (v === "deny") return t("fmt.deny");
  return String(v);
}

/** Libellé d'un réglage : anglais côté console, français fourni par le serveur. */
function useLabel() {
  const { lang } = useI18n();
  return (key: string, fromServer: { title: string; help: string }) =>
    (lang === "en" && settingLabelsEn[key]) || fromServer;
}

function History({ data }: { data: Data }) {
  const { t } = useI18n();
  const label = useLabel();
  const names: Record<string, string> = {
    ...Object.fromEntries(Object.entries({ ...data.labels, ...data.type_labels, ...data.decision_labels }).map(([k, l]) => [k, label(k, l).title])),
    ner_threshold: t("hist.ner_threshold"), allowlist_extra: t("hist.allowlist_extra"), pii_tables: t("hist.pii_tables"),
    web_deny_domains_extra: t("hist.web_deny_domains_extra"),
  };
  if (!data.history.length) return <p className="px-6 py-4 text-sm text-slate-400">{t("hist.none")}</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {data.history.slice(0, 10).map((h, i) => (
        <li key={i} className="flex items-start gap-4 px-6 py-3 text-sm">
          <span className="w-28 shrink-0 text-xs text-slate-400 tabular-nums">{formatDate(h.ts)}</span>
          <div className="min-w-0 flex-1 text-slate-600">
            {h.action === "reset" && <Badge className="mr-1">{t("common.defaults")}</Badge>}
            {h.changes.map((c) => `${names[c.sub ?? c.key] ?? c.sub ?? c.key}: ${fmt(c.old, t)} → ${fmt(c.new, t)}`).join(" ; ")}
          </div>
          {h.reduces && <Badge tone="warning" dot>{t("hist.reduced")}</Badge>}
        </li>
      ))}
    </ul>
  );
}

const boolIcons: Record<BoolSettingKey, React.ReactNode> = {
  mask_amounts: <Banknote className="size-4" />,
  allow_images: <Image className="size-4" />,
  ner_documents: <BrainCircuit className="size-4" />,
  ner_tool_results: <BrainCircuit className="size-4" />,
};

export default function Settings() {
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorState error={error} />;
  return <SettingsBody data={data} />;
}

function SettingsBody({ data }: { data: Data }) {
  const { t, r } = useI18n();
  const label = useLabel();
  const { save, pending } = useSave(data);
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const s = data.settings, d = data.defaults;
  const boolRow = (k: BoolSettingKey) => (
    <Row key={k} icon={boolIcons[k]} title={label(k, data.labels[k]).title} help={label(k, data.labels[k]).help} changed={s[k] !== d[k]}>
      <Switch label={label(k, data.labels[k]).title} checked={s[k]} disabled={pending} onChange={(v) => save({ [k]: v })} />
    </Row>
  );
  const reset = async () => {
    if (!(await confirm({ title: t("set.resetTitle"), confirmLabel: t("set.resetConfirm"), tone: "primary",
      message: t("set.resetMsg") }))) return;
    try { await api.resetSettings(); qc.invalidateQueries({ queryKey: ["settings"] }); toast(t("set.resetDone")); }
    catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <>
      <PageHeader title={t("set.title")} description={t("set.description")}
        actions={<Button icon={<RotateCcw className="size-4" />} onClick={reset}>{t("common.defaults")}</Button>} />
      {!data.policy_loaded && (
        <div className="mb-6"><Alert tone="warning" icon={<AlertTriangle className="size-4" />} title={t("set.policyMissing.title")}>
          {t("set.policyMissing.body")}
        </Alert></div>
      )}
      <ProviderCard />

      <Section icon={<EyeOff className="size-4" />} title={t("set.masked.title")}
        description={t("set.masked.desc")}>
        {boolRow("mask_amounts")}
        {Object.entries(data.type_labels).map(([type, l]) => (
          <Row key={type} title={label(type, l).title} help={label(type, l).help} changed={s.mask_types[type] !== d.mask_types[type]}>
            <Switch label={label(type, l).title} checked={!!s.mask_types[type]} disabled={pending} onChange={(v) => save({ mask_types: { [type]: v } })} />
          </Row>
        ))}
        {boolRow("allow_images")}
        <li className="flex items-center gap-2 bg-slate-50/60 px-6 py-3 text-xs text-slate-500">
          <Lock className="size-3.5" /> {t("set.masked.always")}
        </li>
      </Section>

      <Section icon={<BrainCircuit className="size-4" />} title={t("set.ner.title")}
        description={t("set.ner.desc")}>
        {boolRow("ner_documents")}
        {boolRow("ner_tool_results")}
        <ThresholdRow data={data} save={save} pending={pending} />
      </Section>

      <Section icon={<ListX className="size-4" />} title={t("set.exceptions.title")}
        description={t("set.exceptions.desc")}>
        <li className="space-y-3 px-6 py-4">
          <ListEditor value={s.allowlist_extra} onSave={(v) => save({ allowlist_extra: v })} pending={pending} placeholder={t("set.exceptions.placeholder")} />
          <p className="text-xs text-slate-400">{t("set.exceptions.locked", { list: data.locked.allowlist.join(", ") })}</p>
        </li>
      </Section>

      <Section icon={<MessageCircleQuestion className="size-4" />} title={t("set.actions.title")}
        description={t("set.actions.desc")}>
        {Object.entries(data.decision_labels).map(([k, l]) => (
          <Row key={k} title={label(k, l).title} help={label(k, l).help} changed={s.decisions[k] !== d.decisions[k]}>
            <Segmented value={s.decisions[k]} disabled={pending} onChange={(v) => save({ decisions: { [k]: v } })} />
          </Row>
        ))}
        <li className="space-y-2 px-6 py-4">
          <p className="text-sm font-medium text-slate-900">{t("set.tables.title")} {!sameList(s.pii_tables, d.pii_tables) && <Badge tone="warning" className="ml-1">{t("common.modified")}</Badge>}</p>
          <p className="text-sm text-slate-500">{t("set.tables.desc")}</p>
          <ListEditor value={s.pii_tables} defaults={d.pii_tables} onSave={(v) => save({ pii_tables: v })} pending={pending} placeholder={t("set.tables.placeholder")} />
        </li>
      </Section>

      <Section icon={<Globe className="size-4" />} title={t("set.web.title")}
        description={t("set.web.desc")}>
        <li className="space-y-3 px-6 py-4">
          <div className="flex flex-wrap items-center gap-1.5">
            <Lock className="size-3.5 text-slate-400" />
            {data.locked.web_deny_domains.map((x) => <span key={x} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">{x}</span>)}
          </div>
          <ListEditor value={s.web_deny_domains_extra} onSave={(v) => save({ web_deny_domains_extra: v })} pending={pending} placeholder={t("set.web.placeholder")} />
        </li>
      </Section>

      <Card padded={false} className="mb-6">
        <div className="px-6 pt-6"><CardHeader icon={<History_ className="size-4" />} title={t("set.history")} /></div>
        <div className="border-t border-slate-100"><History data={data} /></div>
      </Card>

      <p className="text-sm text-slate-500">
        {r("set.locked", undefined, "rounded bg-slate-100 px-1.5 py-0.5 text-xs")}
      </p>
    </>
  );
}
