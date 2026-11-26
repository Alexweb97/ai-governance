import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, AlertTriangle, BookText, BrainCircuit, Cpu, ExternalLink, EyeOff, Ban, Lock, MessageCircleQuestion, RefreshCw, Server,
} from "lucide-react";
import { api, formatDate, type GovEvent } from "../lib/api";
import { Alert, Badge, Card, EmptyState, ErrorState, PageHeader, PageLoader } from "../components/ui";
import { describeProvider } from "../lib/provider";
import { useI18n } from "../i18n";
import type { Key } from "../i18n/en";

const kindMeta: Record<GovEvent["kind"], { label: Key; tone: "danger" | "warning" | "brand" | "neutral"; icon: typeof Ban }> = {
  deny: { label: "kind.deny", tone: "danger", icon: Ban },
  ask: { label: "kind.ask", tone: "warning", icon: MessageCircleQuestion },
  pseudo: { label: "kind.pseudo", tone: "brand", icon: EyeOff },
  config: { label: "kind.config", tone: "neutral", icon: RefreshCw },
  c3: { label: "kind.c3", tone: "danger", icon: Lock },
};

const EVENT_LABELS = new Set(["deny", "block", "ask", "warn", "pii_pseudonymized", "request_blocked", "config_reloaded",
  "config_changed", "settings_changed", "c3_blocked", "pass"]);

function StatCard({ icon, label, value, sub, tone }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub: React.ReactNode; tone: "ok" | "bad" | "neutral" }) {
  return (
    <Card className="relative overflow-hidden">
      <div className={clsx("absolute inset-x-0 top-0 h-1", tone === "ok" ? "bg-emerald-500" : tone === "bad" ? "bg-rose-500" : "bg-brand-500")} />
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <div className="text-slate-400">{icon}</div>
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-tight text-slate-900">{value}</p>
      <p className="mt-1 text-sm text-slate-500">{sub}</p>
    </Card>
  );
}

export default function Dashboard() {
  const { t, r } = useI18n();
  const { data, error, isLoading, isFetching } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 10000 });
  const [filter, setFilter] = useState<GovEvent["kind"] | "all">("all");
  const [limit, setLimit] = useState(15);
  const events = useMemo(() => (data?.events ?? []).filter((e) => filter === "all" || e.kind === filter), [data, filter]);
  const counts = useMemo(() => {
    const c = { deny: 0, ask: 0, pseudo: 0, config: 0, c3: 0 };
    data?.events.forEach((e) => { c[e.kind]++; });
    return c;
  }, [data]);

  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorState error={error} />;
  const h = data.health;
  const provider = describeProvider(data.provider.selected, data.provider, t);
  const eventLabel = (l: string) => (EVENT_LABELS.has(l) ? t(`event.${l}` as Key) : l);

  return (
    <>
      <PageHeader title={t("dash.title")} description={t("dash.description")}
        actions={<a href={data.grafana_url} target="_blank" rel="noopener noreferrer"
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3.5 text-sm font-medium text-slate-700 shadow-xs ring-1 ring-slate-200 hover:bg-slate-50">
          Grafana <ExternalLink className="size-3.5" /></a>} />

      {!h.ok && (
        <div className="mb-6"><Alert title={t("dash.proxyDown.title")} icon={<AlertTriangle className="size-4" />}>
          {r("dash.proxyDown.body", undefined, "rounded bg-rose-100 px-1")}
        </Alert></div>
      )}
      {data.clients.undeclared.length > 0 && (
        <div className="mb-6"><Alert tone="warning" title={t("dash.undeclared.title")} icon={<AlertTriangle className="size-4" />}>
          {data.clients.undeclared.map((c, i) => <span key={c}>{i > 0 && ", "}<Link className="font-medium underline" to={`/clients/${c}`}>{c}</Link></span>)}
          {" "}{t("dash.undeclared.suffix")}
        </Alert></div>
      )}

      <div className="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Server className="size-4" />} label={t("stat.proxy")} tone={h.ok ? "ok" : "bad"}
          value={h.ok ? t("stat.proxyOk") : t("stat.proxyDown")} sub={h.ok ? t("stat.pseudoActive") : h.error ?? t("stat.unreachable")} />
        <StatCard icon={<BrainCircuit className="size-4" />} label={t("stat.ner")} tone={h.presidio === "ok" ? "ok" : "bad"}
          value={h.presidio === "ok" ? t("stat.nerActive") : t("stat.nerDown")} sub={t("stat.nerSub")} />
        <StatCard icon={<BookText className="size-4" />} label={t("stat.dictionary")} tone="neutral"
          value={t("stat.terms", { count: h.terms ?? 0 })} sub={t("stat.dictSub", { clients: data.clients.declared, tenders: data.clients.consultations })} />
        <StatCard icon={<Cpu className="size-4" />} label={t("stat.model")}
          tone={data.provider.selected === "trusted" && h.trusted !== "ok" ? "bad" : "neutral"}
          value={provider.name}
          sub={data.provider.selected === "trusted"
            ? (h.trusted ? t(`trusted.${h.trusted}` as Key, { detail: provider.detail }) : provider.detail)
            : t("stat.claudeSub")} />
      </div>

      <Card padded={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-slate-400" />
            <h2 className="text-[15px] font-semibold">{t("dash.log")}</h2>
            {isFetching && <RefreshCw className="size-3.5 animate-spin text-slate-300" />}
          </div>
          <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
            {(["all", "deny", "ask", "pseudo", "c3", "config"] as const).map((k) => (
              <button key={k} onClick={() => { setFilter(k); setLimit(15); }}
                className={clsx("rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  filter === k ? "bg-white text-slate-900 shadow-xs" : "text-slate-500 hover:text-slate-700")}>
                {k === "all" ? t("dash.all") : t(kindMeta[k].label)}
                <span className="ml-1.5 text-slate-400">{k === "all" ? data.events.length : counts[k]}</span>
              </button>
            ))}
          </div>
        </div>
        {events.length === 0 ? (
          <div className="p-6"><EmptyState icon={<Activity className="size-5" />} title={t("dash.empty.title")}
            description={t("dash.empty.desc")} /></div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {events.slice(0, limit).map((e, i) => {
              const m = kindMeta[e.kind];
              const Icon = m.icon;
              return (
                <li key={i} className="flex items-start gap-4 px-6 py-3.5 hover:bg-slate-50/60">
                  <div className={clsx("mt-0.5 rounded-lg p-1.5", {
                    "bg-rose-50 text-rose-600": e.kind === "deny", "bg-amber-50 text-amber-600": e.kind === "ask",
                    "bg-brand-50 text-brand-600": e.kind === "pseudo", "bg-slate-100 text-slate-500": e.kind === "config",
                    "bg-violet-50 text-violet-600": e.kind === "c3" })}>
                    <Icon className="size-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-slate-900">{eventLabel(e.label)}</p>
                      {e.tool && e.tool !== "proxy" && <Badge>{e.tool}</Badge>}
                      {e.provider === "trusted" && <Badge tone="brand">{t("dash.trustedBadge")}</Badge>}
                      {e.model && <span className="text-xs text-slate-400">{e.model}</span>}
                    </div>
                    {Object.keys(e.counts).length > 0 ? (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {Object.entries(e.counts).sort().map(([t, n]) => (
                          <span key={t} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{t} × {n}</span>
                        ))}
                      </div>
                    ) : e.details && <p className="mt-0.5 truncate text-sm text-slate-500" title={e.details}>{e.details}</p>}
                  </div>
                  <time className="shrink-0 text-xs tabular-nums text-slate-400">{formatDate(e.ts)}</time>
                </li>
              );
            })}
          </ul>
        )}
        {events.length > limit && (
          <div className="border-t border-slate-100 px-6 py-3 text-center">
            <button onClick={() => setLimit((l) => l + 30)} className="text-sm font-medium text-brand-600 hover:text-brand-700">
              {t("dash.showMore", { count: events.length - limit })}
            </button>
          </div>
        )}
      </Card>
    </>
  );
}
