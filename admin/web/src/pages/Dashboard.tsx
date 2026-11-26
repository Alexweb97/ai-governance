import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, AlertTriangle, BookText, BrainCircuit, Cpu, ExternalLink, EyeOff, Ban, Lock, MessageCircleQuestion, RefreshCw, Server,
} from "lucide-react";
import { api, formatDate, type GovEvent } from "../lib/api";
import { Alert, Badge, Card, EmptyState, ErrorState, PageHeader, PageLoader } from "../components/ui";

const kindMeta: Record<GovEvent["kind"], { label: string; tone: "danger" | "warning" | "brand" | "neutral"; icon: typeof Ban }> = {
  deny: { label: "Refusé", tone: "danger", icon: Ban },
  ask: { label: "Confirmation", tone: "warning", icon: MessageCircleQuestion },
  pseudo: { label: "Pseudonymisé", tone: "brand", icon: EyeOff },
  config: { label: "Configuration", tone: "neutral", icon: RefreshCw },
  c3: { label: "Accès C3", tone: "danger", icon: Lock },
};

const labels: Record<string, string> = {
  deny: "Action refusée", block: "Prompt bloqué", ask: "Confirmation demandée", warn: "Données signalées",
  pii_pseudonymized: "Requête pseudonymisée", request_blocked: "Requête bloquée",
  config_reloaded: "Configuration rechargée", config_changed: "Configuration modifiée", settings_changed: "Réglage modifié (console)",
  c3_blocked: "Envoi à Anthropic bloqué (C3)", pass: "Accès C3 autorisé (fournisseur de confiance)",
};

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

  return (
    <>
      <PageHeader title="Tableau de bord" description="État de la protection et dernières décisions de la gouvernance."
        actions={<a href={data.grafana_url} target="_blank" rel="noopener noreferrer"
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3.5 text-sm font-medium text-slate-700 shadow-xs ring-1 ring-slate-200 hover:bg-slate-50">
          Grafana <ExternalLink className="size-3.5" /></a>} />

      {!h.ok && (
        <div className="mb-6"><Alert title="Le proxy ne répond pas" icon={<AlertTriangle className="size-4" />}>
          Claude Code ne peut plus joindre l'API (fail-closed). Relancez la stack : <code className="rounded bg-rose-100 px-1">docker compose up -d</code>
        </Alert></div>
      )}
      {data.clients.undeclared.length > 0 && (
        <div className="mb-6"><Alert tone="warning" title="Dossiers clients non déclarés" icon={<AlertTriangle className="size-4" />}>
          {data.clients.undeclared.map((c, i) => <span key={c}>{i > 0 && ", "}<Link className="font-medium underline" to={`/clients/${c}`}>{c}</Link></span>)}
          {" "}— leur nom n'est pas masqué.
        </Alert></div>
      )}

      <div className="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Server className="size-4" />} label="Proxy" tone={h.ok ? "ok" : "bad"}
          value={h.ok ? "Opérationnel" : "En panne"} sub={h.ok ? "Pseudonymisation active" : h.error ?? "Injoignable"} />
        <StatCard icon={<BrainCircuit className="size-4" />} label="Détection des noms" tone={h.presidio === "ok" ? "ok" : "bad"}
          value={h.presidio === "ok" ? "Active" : "Indisponible"} sub="Presidio · NER français" />
        <StatCard icon={<BookText className="size-4" />} label="Dictionnaire" tone="neutral"
          value={`${h.terms ?? 0} termes`} sub={`${data.clients.declared} client(s) · ${data.clients.consultations} consultation(s)`} />
        <StatCard icon={<Cpu className="size-4" />} label="Modèle d'IA"
          tone={data.provider.selected === "trusted" && h.trusted !== "ok" ? "bad" : "neutral"}
          value={data.provider.name}
          sub={data.provider.selected === "trusted"
            ? ({ ok: `${data.provider.detail} · joignable`, not_configured: "TRUSTED_URL ou TRUSTED_MODEL non défini",
                 key_missing: "Clé TRUSTED_API_KEY absente", auth_error: "Clé refusée par le fournisseur",
                 down: "Fournisseur injoignable" } as Record<string, string>)[h.trusted ?? ""] ?? data.provider.detail
            : "Anthropic · abonnement Claude"} />
      </div>

      <Card padded={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-slate-400" />
            <h2 className="text-[15px] font-semibold">Journal des décisions</h2>
            {isFetching && <RefreshCw className="size-3.5 animate-spin text-slate-300" />}
          </div>
          <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
            {(["all", "deny", "ask", "pseudo", "c3", "config"] as const).map((k) => (
              <button key={k} onClick={() => { setFilter(k); setLimit(15); }}
                className={clsx("rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  filter === k ? "bg-white text-slate-900 shadow-xs" : "text-slate-500 hover:text-slate-700")}>
                {k === "all" ? "Tout" : kindMeta[k].label}
                <span className="ml-1.5 text-slate-400">{k === "all" ? data.events.length : counts[k]}</span>
              </button>
            ))}
          </div>
        </div>
        {events.length === 0 ? (
          <div className="p-6"><EmptyState icon={<Activity className="size-5" />} title="Aucun événement"
            description="Les refus, confirmations et pseudonymisations apparaîtront ici dès votre prochaine session Claude Code." /></div>
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
                      <p className="text-sm font-medium text-slate-900">{labels[e.label] ?? e.label}</p>
                      {e.tool && e.tool !== "proxy" && <Badge>{e.tool}</Badge>}
                      {e.provider === "trusted" && <Badge tone="brand">Confiance</Badge>}
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
              Afficher plus ({events.length - limit} restants)
            </button>
          </div>
        )}
      </Card>
    </>
  );
}
