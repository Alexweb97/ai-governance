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

function C3Sessions() {
  const { data } = useQuery({ queryKey: ["c3"], queryFn: api.c3Sessions, refetchInterval: 10000 });
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const sessions = data?.sessions ?? [];
  if (!sessions.length) return null;
  const open = sessions.filter((s) => s.open);
  const close = async (id: string, short: string) => {
    if (!(await confirm({ title: `Clôturer la session ${short} ?`, confirmLabel: "Clôturer", tone: "primary",
      message: <>À faire si Claude Code a été fermé sans <code className="rounded bg-slate-100 px-1">/exit</code>. La session restera <strong>définitivement bloquée</strong> vers Anthropic, même si elle est reprise.</> }))) return;
    try { await api.closeC3Session(id); qc.invalidateQueries(); toast("Session clôturée"); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="mt-6 rounded-xl ring-1 ring-violet-200 bg-violet-50/40">
      <div className="flex items-start gap-3 px-5 pt-4">
        <Lock className="mt-0.5 size-4 text-violet-600" />
        <div>
          <p className="text-sm font-semibold text-slate-900">Sessions C3 {open.length > 0 && <Badge tone="danger" className="ml-1">{open.length} ouverte(s)</Badge>}</p>
          <p className="mt-0.5 text-sm text-slate-600">
            Sessions ayant lu du contenu C3 avec le fournisseur de confiance. Elles ne seront <strong>jamais</strong> envoyées à Anthropic, même reprises.
            {open.length > 0 && " Le retour à Claude est bloqué tant qu'elles sont ouvertes."}
          </p>
        </div>
      </div>
      <ul className="mt-3 divide-y divide-violet-100 border-t border-violet-100">
        {sessions.slice(0, 8).map((s) => (
          <li key={s.id} className="flex items-center gap-4 px-5 py-2.5 text-sm">
            <code className="font-mono text-xs text-slate-700">{s.short}</code>
            <span className="min-w-0 flex-1 truncate text-slate-500" title={s.cwd}>{s.cwd}</span>
            <span className="text-xs text-slate-400 tabular-nums">{s.accesses} accès · {formatDate(s.last)}</span>
            {s.open ? <><Badge tone="danger" dot>Ouverte</Badge><Button size="sm" variant="ghost" onClick={() => close(s.id, s.short)}>Clôturer</Button></>
              : <Badge dot>Fermée</Badge>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ProviderCard() {
  const { data } = useQuery({ queryKey: ["provider"], queryFn: api.provider });
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const m = useMutation({
    mutationFn: (p: ProviderId) => api.setProvider(p),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast(`Fournisseur : ${data?.providers[r.provider]?.name ?? r.provider} — appliqué dans quelques secondes`);
    },
    onError: (e) => toast(e.message, "error"),
  });
  if (!data) return null;
  const choose = async (p: ProviderId) => {
    if (p === data.provider) return;
    const info = data.providers[p];
    if (await confirm({
      title: `Basculer vers ${info.name} ?`, confirmLabel: `Utiliser ${info.name}`, tone: "primary",
      message: <div className="space-y-2">
        <p>Toutes les sessions Claude Code utiliseront <strong>{info.name}</strong> ({info.detail}).</p>
        <p>Lancez ensuite une <strong>nouvelle session</strong> (ou <code className="rounded bg-slate-100 px-1">/clear</code>) : l'historique d'une session ne passe pas proprement d'un modèle à l'autre.</p>
        {p === "trusted" ? <p>Les dossiers <strong>C3</strong> deviendront lisibles ; toute session qui y accède sera marquée et ne pourra jamais être envoyée à Anthropic.</p>
          : <p>Les dossiers <strong>C3</strong> redeviendront illisibles. Les sessions marquées C3 resteront bloquées vers Anthropic.</p>}
      </div>,
    })) m.mutate(p);
  };
  return (
    <Card className="mb-6">
      <CardHeader icon={<Cpu className="size-4" />} title="Modèle d'IA"
        description="Fournisseur utilisé par Claude Code, pour toutes les sessions. La pseudonymisation reste active dans les deux cas." />
      <div className="grid gap-4 md:grid-cols-2">
        {(Object.keys(data.providers) as ProviderId[]).map((p) => {
          const info = data.providers[p];
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
          Les dossiers <code>_confidentiel</code> (C3) ne sont lisibles qu'avec le fournisseur de confiance. Selon le modèle choisi, il peut être moins performant que Claude sur le code et les tâches longues, et son contexte plus court. Ne choisissez comme fournisseur de confiance qu'un service à qui vous confiez vraiment ces données.
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
function reduces(patch: Partial<S>, cur: S): string[] {
  const out: string[] = [];
  for (const k of ["mask_amounts", "ner_documents", "ner_tool_results"] as const)
    if (k in patch && cur[k] && patch[k] === false) out.push("une détection est désactivée");
  if (patch.allow_images && !cur.allow_images) out.push("les images seront envoyées telles quelles");
  if (patch.ner_threshold !== undefined && patch.ner_threshold > cur.ner_threshold) out.push("moins de noms seront détectés");
  if (patch.mask_types && Object.entries(patch.mask_types).some(([t, v]) => cur.mask_types[t] && !v)) out.push("un type de donnée ne sera plus masqué");
  if (patch.decisions && Object.entries(patch.decisions).some(([d, v]) => cur.decisions[d] === "deny" && v === "ask")) out.push("une action refusée deviendra possible après confirmation");
  if (patch.allowlist_extra && patch.allowlist_extra.some((v) => !cur.allowlist_extra.includes(v))) out.push("de nouveaux termes seront envoyés en clair");
  if (patch.pii_tables && cur.pii_tables.some((v) => !patch.pii_tables!.includes(v))) out.push("des tables ne seront plus surveillées");
  if (patch.web_deny_domains_extra && cur.web_deny_domains_extra.some((v) => !patch.web_deny_domains_extra!.includes(v))) out.push("des domaines ne seront plus bloqués");
  return [...new Set(out)];
}

function useSave(data: Data) {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const m = useMutation({
    mutationFn: (patch: Partial<S>) => api.updateSettings(patch),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["status"] }); toast("Réglage enregistré : appliqué au proxy et aux hooks dans quelques secondes"); },
    onError: (e) => toast(e.message, "error"),
  });
  const save = async (patch: Partial<S>) => {
    const why = reduces(patch, data.settings);
    if (why.length && !(await confirm({
      title: "Réduire la protection ?", confirmLabel: "Confirmer", tone: "danger",
      message: <div className="space-y-2"><p>Ce changement affaiblit la gouvernance : {why.join(" ; ")}.</p>
        <p>Il sera inscrit dans l'historique des réglages et dans le tableau de bord.</p></div>,
    }))) return false;
    await m.mutateAsync(patch).catch(() => {});
    return true;
  };
  return { save, pending: m.isPending };
}

function Row({ icon, title, help, children, changed }:
  { icon?: React.ReactNode; title: string; help?: React.ReactNode; children: React.ReactNode; changed?: boolean }) {
  return (
    <li className="flex items-center justify-between gap-6 px-6 py-4">
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 rounded-lg bg-slate-100 p-2 text-slate-600">{icon}</div>}
        <div>
          <p className="text-sm font-medium text-slate-900">{title} {changed && <Badge tone="warning" className="ml-1">modifié</Badge>}</p>
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
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const dirty = !sameList(draft, value);
  return (
    <div className="space-y-2">
      <TagInput value={draft} onChange={setDraft} placeholder={placeholder} />
      <div className="flex justify-end gap-2">
        {defaults && !sameList(draft, defaults) && <Button size="sm" variant="ghost" onClick={() => setDraft(defaults)}>Valeurs par défaut</Button>}
        {dirty && <Button size="sm" variant="ghost" onClick={() => setDraft(value)}>Annuler</Button>}
        <Button size="sm" variant="primary" icon={<Save className="size-3.5" />} disabled={!dirty} loading={pending}
          onClick={async () => { if (!(await onSave(draft))) setDraft(value); }}>Enregistrer</Button>
      </div>
    </div>
  );
}

function Segmented({ value, onChange, disabled }: { value: Decision; onChange: (v: Decision) => void; disabled?: boolean }) {
  const opts: { v: Decision; label: string }[] = [{ v: "ask", label: "Demander" }, { v: "deny", label: "Refuser" }];
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
  const cur = data.settings.ner_threshold;
  const [v, setV] = useState(cur);
  useEffect(() => setV(cur), [cur]);
  return (
    <Row icon={<Gauge className="size-4" />} title="Seuil de détection des noms" changed={cur !== data.defaults.ner_threshold}
      help={<>Plus bas : davantage de noms masqués, avec plus de faux positifs. Plus haut : moins de faux positifs, mais des noms peuvent passer. Défaut : {data.defaults.ner_threshold.toFixed(2)}.</>}>
      <div className="flex items-center gap-3">
        <input type="range" min={0.5} max={0.95} step={0.05} value={v} onChange={(e) => setV(Number(e.target.value))}
          className="w-36 accent-brand-600" aria-label="Seuil de détection des noms" />
        <span className="w-10 text-right font-mono text-sm tabular-nums">{v.toFixed(2)}</span>
        <Button size="sm" variant="primary" disabled={v === cur} loading={pending}
          onClick={async () => { if (!(await save({ ner_threshold: v }))) setV(cur); }}>Appliquer</Button>
      </div>
    </Row>
  );
}

function fmt(v: unknown): string {
  if (typeof v === "boolean") return v ? "oui" : "non";
  if (Array.isArray(v)) return `${v.length} entrée(s)`;
  if (v === "ask") return "demander";
  if (v === "deny") return "refuser";
  return String(v);
}

function History({ data }: { data: Data }) {
  const names: Record<string, string> = {
    ...Object.fromEntries(Object.entries({ ...data.labels, ...data.type_labels, ...data.decision_labels }).map(([k, l]) => [k, l.title])),
    ner_threshold: "Seuil de détection", allowlist_extra: "Exceptions", pii_tables: "Tables de données personnelles",
    web_deny_domains_extra: "Domaines interdits",
  };
  if (!data.history.length) return <p className="px-6 py-4 text-sm text-slate-400">Aucune modification depuis l'installation.</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {data.history.slice(0, 10).map((h, i) => (
        <li key={i} className="flex items-start gap-4 px-6 py-3 text-sm">
          <span className="w-28 shrink-0 text-xs text-slate-400 tabular-nums">{formatDate(h.ts)}</span>
          <div className="min-w-0 flex-1 text-slate-600">
            {h.action === "reset" && <Badge className="mr-1">Valeurs par défaut</Badge>}
            {h.changes.map((c) => `${names[c.sub ?? c.key] ?? c.sub ?? c.key} : ${fmt(c.old)} → ${fmt(c.new)}`).join(" ; ")}
          </div>
          {h.reduces && <Badge tone="warning" dot>Protection réduite</Badge>}
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
  const { save, pending } = useSave(data);
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const s = data.settings, d = data.defaults;
  const boolRow = (k: BoolSettingKey) => (
    <Row key={k} icon={boolIcons[k]} title={data.labels[k].title} help={data.labels[k].help} changed={s[k] !== d[k]}>
      <Switch label={data.labels[k].title} checked={s[k]} disabled={pending} onChange={(v) => save({ [k]: v })} />
    </Row>
  );
  const reset = async () => {
    if (!(await confirm({ title: "Revenir aux valeurs par défaut ?", confirmLabel: "Réinitialiser", tone: "primary",
      message: "Tous les réglages ci-dessus reprennent les valeurs de policy.json. Le modèle d'IA choisi n'est pas modifié." }))) return;
    try { await api.resetSettings(); qc.invalidateQueries({ queryKey: ["settings"] }); toast("Valeurs par défaut rétablies"); }
    catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <>
      <PageHeader title="Réglages" description="Appliqués à chaud au proxy et aux hooks, sans redémarrage. Chaque modification est historisée."
        actions={<Button icon={<RotateCcw className="size-4" />} onClick={reset}>Valeurs par défaut</Button>} />
      {!data.policy_loaded && (
        <div className="mb-6"><Alert tone="warning" icon={<AlertTriangle className="size-4" />} title="policy.json non lu par la console">
          Les valeurs par défaut affichées sont approximatives. Relancez la console (make rebuild-admin).
        </Alert></div>
      )}
      <ProviderCard />

      <Section icon={<EyeOff className="size-4" />} title="Données masquées"
        description="Remplacées par des jetons avant tout envoi au modèle, puis restituées dans ses réponses.">
        {boolRow("mask_amounts")}
        {Object.entries(data.type_labels).map(([t, l]) => (
          <Row key={t} title={l.title} help={l.help} changed={s.mask_types[t] !== d.mask_types[t]}>
            <Switch label={l.title} checked={!!s.mask_types[t]} disabled={pending} onChange={(v) => save({ mask_types: { [t]: v } })} />
          </Row>
        ))}
        {boolRow("allow_images")}
        <li className="flex items-center gap-2 bg-slate-50/60 px-6 py-3 text-xs text-slate-500">
          <Lock className="size-3.5" /> Clés d'API, mots de passe et clés privées : toujours masqués, non réglable.
        </li>
      </Section>

      <Section icon={<BrainCircuit className="size-4" />} title="Détection des noms de personnes"
        description="Détection automatique (NER) des noms et des lieux, en plus du dictionnaire des clients.">
        {boolRow("ner_documents")}
        {boolRow("ner_tool_results")}
        <ThresholdRow data={data} save={save} pending={pending} />
      </Section>

      <Section icon={<ListX className="size-4" />} title="Exceptions"
        description="Termes à ne jamais masquer : nom de produit public, ville, collègue pris pour une donnée sensible. Un nom du dictionnaire des clients est refusé.">
        <li className="space-y-3 px-6 py-4">
          <ListEditor value={s.allowlist_extra} onSave={(v) => save({ allowlist_extra: v })} pending={pending} placeholder="Ajouter un terme puis Entrée" />
          <p className="text-xs text-slate-400">Toujours exclus (policy.json) : {data.locked.allowlist.join(", ")}</p>
        </li>
      </Section>

      <Section icon={<MessageCircleQuestion className="size-4" />} title="Actions sensibles"
        description="Demander : Claude Code vous demande de confirmer. Refuser : l'action est bloquée.">
        {Object.entries(data.decision_labels).map(([k, l]) => (
          <Row key={k} title={l.title} help={l.help} changed={s.decisions[k] !== d.decisions[k]}>
            <Segmented value={s.decisions[k]} disabled={pending} onChange={(v) => save({ decisions: { [k]: v } })} />
          </Row>
        ))}
        <li className="space-y-2 px-6 py-4">
          <p className="text-sm font-medium text-slate-900">Tables contenant des données personnelles {!sameList(s.pii_tables, d.pii_tables) && <Badge tone="warning" className="ml-1">modifié</Badge>}</p>
          <p className="text-sm text-slate-500">Une requête SQL sur ces tables (Bash ou outil MCP) déclenche la décision ci-dessus.</p>
          <ListEditor value={s.pii_tables} defaults={d.pii_tables} onSave={(v) => save({ pii_tables: v })} pending={pending} placeholder="Nom de table puis Entrée" />
        </li>
      </Section>

      <Section icon={<Globe className="size-4" />} title="Domaines web interdits"
        description="WebFetch refusé vers ces domaines et leurs sous-domaines (sites d'exfiltration).">
        <li className="space-y-3 px-6 py-4">
          <div className="flex flex-wrap items-center gap-1.5">
            <Lock className="size-3.5 text-slate-400" />
            {data.locked.web_deny_domains.map((x) => <span key={x} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">{x}</span>)}
          </div>
          <ListEditor value={s.web_deny_domains_extra} onSave={(v) => save({ web_deny_domains_extra: v })} pending={pending} placeholder="Ajouter un domaine puis Entrée" />
        </li>
      </Section>

      <Card padded={false} className="mb-6">
        <div className="px-6 pt-6"><CardHeader icon={<History_ className="size-4" />} title="Historique des réglages" /></div>
        <div className="border-t border-slate-100"><History data={data} /></div>
      </Card>

      <p className="text-sm text-slate-500">
        Non réglables ici, par sécurité : fichiers sensibles, verrou C3, commandes interdites, mode fail-closed. Voir <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">policy/policy.json</code> puis <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">make hooks</code>.
      </p>
    </>
  );
}
