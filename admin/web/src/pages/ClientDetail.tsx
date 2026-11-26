import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FileText, Lock, Plus, Save, ShieldOff, Tags } from "lucide-react";
import { api, type Client } from "../lib/api";
import { useToast } from "../lib/toast";
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
  const [ref, setRef] = useState("");
  const [title, setTitle] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const m = useMutation({
    mutationFn: () => api.createConsultation(code, { ref, title }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast(`Consultation ${r.ref} créée`);
      navigate(`/clients/${code}/${r.ref}`);
    },
  });
  return (
    <Modal open onClose={onClose} title="Nouvelle consultation"
      description="Crée travail/DCE, travail/memoire-technique et _confidentiel."
      footer={<><Button onClick={onClose}>Annuler</Button>
        <Button variant="primary" loading={m.isPending} disabled={!ref} onClick={() => m.mutate()}>Créer</Button></>}>
      <div className="space-y-4">
        <Field label="Référence (nom du dossier)" hint="Sans le nom du client : elle apparaît dans les chemins. Ex. AO-2026-015">
          <Input value={ref} onChange={(e) => setRef(e.target.value)} className="font-mono" placeholder="AO-2026-015" />
        </Field>
        <Field label="Intitulé du marché (optionnel)" hint="Ajouté au dictionnaire : remplacé par PII_PROJET_…">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Refonte du système d'information" />
        </Field>
        {m.error && <Alert>{m.error.message}</Alert>}
      </div>
    </Modal>
  );
}

function IdentityForm({ client }: { client: Client }) {
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
    onSuccess: () => { qc.invalidateQueries(); toast("Dictionnaire mis à jour : appliqué dans quelques secondes"); },
  });
  return (
    <Card>
      <CardHeader icon={<Tags className="size-4" />} title="Identité masquée"
        description="Tout ce qui figure ici est remplacé par PII_CLIENT_… (casse ignorée, mots entiers)." />
      <div className="space-y-5">
        <Field label="Nom du client"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Variantes" hint="Sigles, versions sans accent, ancien nom, domaines, noms des interlocuteurs côté client…">
          <TagInput value={variants} onChange={setVariants} placeholder="Ajouter une variante puis Entrée" />
        </Field>
        {m.error && <Alert>{m.error.message}</Alert>}
        <div className="flex justify-end">
          <Button variant="primary" icon={<Save className="size-4" />} loading={m.isPending}
            disabled={(!dirty && client.declared) || name.trim().length < 2} onClick={() => m.mutate()}>
            {client.declared ? "Enregistrer" : "Déclarer le client"}
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function ClientDetail() {
  const { code = "" } = useParams();
  const { data: client, error, isLoading } = useQuery({ queryKey: ["client", code], queryFn: () => api.client(code) });
  const [newOpen, setNewOpen] = useState(false);
  const confirm = useConfirm();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const remove = useMutation({
    mutationFn: () => api.deleteClient(code),
    onSuccess: () => { qc.invalidateQueries(); toast(`${code} retiré du dictionnaire`); navigate("/clients"); },
    onError: (e) => toast(e.message, "error"),
  });

  if (isLoading) return <PageLoader />;
  if (error || !client) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader
        breadcrumb={<Breadcrumb items={[{ label: "Clients", to: "/clients" }, { label: client.code }]} />}
        title={<span className="flex items-center gap-3">{client.declared ? client.name : client.code}
          <Badge tone="brand" className="font-mono">{client.code}</Badge></span>}
        description={client.declared ? `${client.variants.length} variante(s) masquée(s) · ${client.consultations.length} consultation(s)` : undefined}
        actions={client.declared && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setNewOpen(true)}>Nouvelle consultation</Button>} />

      {!client.declared && (
        <div className="mb-6"><Alert icon={<AlertTriangle className="size-4" />} title="Client non déclaré">
          Ce dossier existe dans ~/clients mais son nom n'est pas masqué. Renseignez-le ci-dessous.
        </Alert></div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
        <Card padded={false}>
          <div className="px-6 pt-6"><CardHeader icon={<FileText className="size-4" />} title="Consultations" /></div>
          {client.consultations.length === 0 ? (
            <div className="px-6 pb-6"><EmptyState icon={<FileText className="size-5" />} title="Aucune consultation"
              action={client.declared && <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setNewOpen(true)}>Créer</Button>} /></div>
          ) : (
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {client.consultations.map((c) => (
                <li key={c.ref}>
                  <Link to={`/clients/${client.code}/${c.ref}`} className="group flex items-center gap-4 px-6 py-4 hover:bg-slate-50/70">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-slate-100 text-slate-500"><FileText className="size-4" /></div>
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-sm font-medium text-slate-900">{c.ref}</p>
                      <p className="truncate text-sm text-slate-500">{c.title || "Sans intitulé"}</p>
                    </div>
                    {c.has_confidential
                      ? <Badge tone="success" dot>C3 en place</Badge>
                      : <Badge tone="warning" dot>Sans _confidentiel</Badge>}
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
              <CardHeader icon={<ShieldOff className="size-4" />} title="Retirer du dictionnaire"
                description="Le nom ne sera plus masqué. Les dossiers et fichiers sont conservés." />
              <Button variant="danger-ghost" icon={<Lock className="size-4" />} loading={remove.isPending}
                onClick={async () => {
                  if (await confirm({ title: `Retirer ${client.code} ?`, confirmLabel: "Retirer",
                    message: <>Le nom <strong>{client.name}</strong> et ses {client.variants.length} variante(s) seront envoyés <strong>en clair</strong> au modèle.</> }))
                    remove.mutate();
                }}>Retirer {client.code}</Button>
            </Card>
          )}
        </div>
      </div>
      {newOpen && <NewConsultationModal code={client.code} onClose={() => setNewOpen(false)} />}
    </>
  );
}
