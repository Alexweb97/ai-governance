import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FolderKanban, Plus, Search } from "lucide-react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, TagInput } from "../components/ui";

function NewClientModal({ open, onClose, nextCode }: { open: boolean; onClose: () => void; nextCode: string }) {
  const [code, setCode] = useState(nextCode);
  const [name, setName] = useState("");
  const [variants, setVariants] = useState<string[]>([]);
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.createClient({ code, name, variants }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast(`Client ${r.code} créé : son nom est masqué dès maintenant`);
      onClose();
      navigate(`/clients/${r.code}`);
    },
  });
  return (
    <Modal open={open} onClose={onClose} size="lg" title="Nouveau client"
      description="Le nom et ses variantes sont ajoutés au dictionnaire et remplacés par un jeton PII_CLIENT_… avant tout envoi."
      footer={<>
        <Button onClick={onClose}>Annuler</Button>
        <Button variant="primary" loading={m.isPending} onClick={() => m.mutate()} disabled={!code || name.trim().length < 2}>Créer le client</Button>
      </>}>
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
          <Field label="Code du dossier" hint="Neutre : il apparaît dans les chemins.">
            <Input value={code} onChange={(e) => setCode(e.target.value)} className="font-mono" />
          </Field>
          <Field label="Nom du client">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="ACME Industries" />
          </Field>
        </div>
        <Field label="Variantes" hint="Entrée pour ajouter. Sigles, versions sans accent, ancien nom, domaines (acme.fr), noms des interlocuteurs…">
          <TagInput value={variants} onChange={setVariants} placeholder="ACME, Société ACME, acme.fr…" />
        </Field>
        {m.error && <Alert>{m.error.message}</Alert>}
      </div>
    </Modal>
  );
}

export default function Clients() {
  const { data, error, isLoading } = useQuery({ queryKey: ["clients"], queryFn: api.clients });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data?.clients ?? []).filter((c) => !s || c.code.toLowerCase().includes(s) || c.name.toLowerCase().includes(s)
      || c.variants.some((v) => v.toLowerCase().includes(s)));
  }, [data, q]);

  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorState error={error} />;
  const undeclared = data.clients.filter((c) => !c.declared);

  return (
    <>
      <PageHeader title="Clients" description="Chaque client déclaré est masqué partout : prompts, documents lus, sorties de commandes."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>Nouveau client</Button>} />

      {undeclared.length > 0 && (
        <div className="mb-6"><Alert tone="warning" icon={<AlertTriangle className="size-4" />} title="Dossiers sans client déclaré">
          {undeclared.map((c) => c.code).join(", ")} — ouvrez-les pour renseigner le nom, sinon il n'est pas masqué.
        </Alert></div>
      )}

      <Card padded={false}>
        <div className="border-b border-slate-100 p-4">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un client, une variante…" className="pl-9" />
          </div>
        </div>
        {filtered.length === 0 ? (
          <div className="p-6"><EmptyState icon={<FolderKanban className="size-5" />}
            title={data.clients.length ? "Aucun résultat" : "Aucun client"}
            description={data.clients.length ? undefined : "Déclarez votre premier client pour commencer à déposer des consultations."}
            action={!data.clients.length && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>Nouveau client</Button>} /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <th className="px-6 py-3 font-medium">Client</th>
                <th className="px-3 py-3 font-medium">Variantes masquées</th>
                <th className="px-3 py-3 font-medium">Consultations</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((c) => (
                <tr key={c.code} className="group hover:bg-slate-50/70">
                  <td className="px-6 py-4">
                    <Link to={`/clients/${c.code}`} className="flex items-center gap-3">
                      <div className="flex size-9 items-center justify-center rounded-lg bg-brand-50 font-mono text-xs font-semibold text-brand-700 ring-1 ring-brand-100">
                        {c.code.slice(0, 4)}
                      </div>
                      <div>
                        <p className="font-medium text-slate-900">{c.declared ? c.name : <Badge tone="danger" dot>Non déclaré</Badge>}</p>
                        <p className="font-mono text-xs text-slate-500">{c.code}</p>
                      </div>
                    </Link>
                  </td>
                  <td className="px-3 py-4">
                    <div className="flex max-w-md flex-wrap gap-1">
                      {c.variants.slice(0, 4).map((v) => <span key={v} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{v}</span>)}
                      {c.variants.length > 4 && <span className="px-1 text-xs text-slate-400">+{c.variants.length - 4}</span>}
                      {c.declared && c.variants.length === 0 && <Badge tone="warning">Aucune variante</Badge>}
                    </div>
                  </td>
                  <td className="px-3 py-4 tabular-nums text-slate-600">{c.consultations.length}</td>
                  <td className="px-6 py-4 text-right">
                    <Link to={`/clients/${c.code}`} className="inline-flex text-slate-300 group-hover:text-slate-500"><ChevronRight className="size-5" /></Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {open && <NewClientModal open onClose={() => setOpen(false)} nextCode={data.next_code} />}
    </>
  );
}
