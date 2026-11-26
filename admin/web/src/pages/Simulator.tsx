import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, FileText, FlaskConical, MessageSquare, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { Alert, Button, Card, CardHeader, PageHeader, Textarea } from "../components/ui";

const SAMPLE = `Réponse au marché d'ACME Industries — référente : Marie Dupont, Lyon.
Montant total : 125 000 € HT, TJM 650. Contact : marie.dupont@acme-industries.fr, 01 23 45 67 89.
IBAN FR76 3000 6000 0112 3456 7890 189 · password = "S3cr3tP@ss!"`;

const typeColor = (t: string) =>
  t.startsWith("SECRET") ? "bg-rose-100 text-rose-800 ring-rose-200"
    : t === "CLIENT" || t === "PROJET" ? "bg-brand-100 text-brand-800 ring-brand-200"
    : t === "MONTANT" ? "bg-amber-100 text-amber-900 ring-amber-200"
    : t === "PERSON" || t === "LOCATION" ? "bg-violet-100 text-violet-800 ring-violet-200"
    : "bg-sky-100 text-sky-800 ring-sky-200";

function Highlighted({ text }: { text: string }) {
  const parts = text.split(/(PII_[A-Z][A-Z0-9_]*?_[0-9a-f]{8})/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = /^PII_([A-Z][A-Z0-9_]*?)_[0-9a-f]{8}$/.exec(p);
        return m ? <span key={i} className={clsx("mx-0.5 rounded px-1 py-0.5 font-mono text-[12px] ring-1 ring-inset", typeColor(m[1]))} title={p}>{m[1]}</span>
          : <span key={i}>{p}</span>;
      })}
    </>
  );
}

export default function Simulator() {
  const [text, setText] = useState(SAMPLE);
  const [scope, setScope] = useState<"user_text" | "document">("document");
  const m = useMutation({ mutationFn: () => api.preview(text, scope) });
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    m.data?.detections.forEach((d) => { c[d.type] = (c[d.type] ?? 0) + 1; });
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [m.data]);

  return (
    <>
      <PageHeader title="Simulateur" description="Collez un extrait de DCE, de mémoire ou de code : vous voyez exactement ce que recevra le modèle, avec la configuration en vigueur." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader icon={<MessageSquare className="size-4" />} title="Texte d'origine" description="Reste sur votre poste." />
          <Textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} className="font-mono text-[13px] leading-relaxed" />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
              {([["document", "Document", FileText], ["user_text", "Prompt", MessageSquare]] as const).map(([k, l, Icon]) => (
                <button key={k} onClick={() => setScope(k)}
                  className={clsx("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium",
                    scope === k ? "bg-white text-slate-900 shadow-xs" : "text-slate-500 hover:text-slate-700")}>
                  <Icon className="size-3.5" /> {l}
                </button>
              ))}
            </div>
            <Button variant="primary" icon={<Sparkles className="size-4" />} loading={m.isPending} onClick={() => m.mutate()} disabled={!text.trim()}>
              Simuler l'envoi
            </Button>
          </div>
        </Card>
        <Card className="flex flex-col">
          <CardHeader icon={<ArrowRight className="size-4" />} title="Ce que reçoit le modèle" description="Les jetons sont restitués en clair à votre retour, jamais côté Anthropic." />
          {m.error && <Alert>{m.error.message}</Alert>}
          {!m.data && !m.error && (
            <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 py-16 text-center">
              <FlaskConical className="mb-3 size-6 text-slate-300" />
              <p className="text-sm text-slate-500">Lancez la simulation pour voir le résultat.</p>
            </div>
          )}
          {m.data && (
            <>
              <div className="flex-1 rounded-xl bg-slate-50 p-4 text-[13px] leading-7 whitespace-pre-wrap text-slate-800 ring-1 ring-slate-100">
                <Highlighted text={m.data.text} />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-slate-700">{m.data.detections.length} élément(s) masqué(s)</span>
                {counts.map(([t, n]) => (
                  <span key={t} className={clsx("rounded-md px-1.5 py-0.5 font-mono text-[11px] ring-1 ring-inset", typeColor(t))}>{t} × {n}</span>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
