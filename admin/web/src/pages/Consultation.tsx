import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowLeftRight, Check, Copy, FileSpreadsheet, FileText, FileType2, File as FileIcon, Lock, Pencil, ShieldCheck, Terminal, Trash2, UploadCloud,
} from "lucide-react";
import { api, formatSize, type FileEntry } from "../lib/api";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, ErrorState, Input, PageHeader, PageLoader, useConfirm } from "../components/ui";
import { Breadcrumb } from "./ClientDetail";

function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return <FileType2 className="size-4 text-rose-500" />;
  if (["xls", "xlsx", "csv", "ods"].includes(ext)) return <FileSpreadsheet className="size-4 text-emerald-600" />;
  if (["doc", "docx", "odt", "md", "txt", "rtf"].includes(ext)) return <FileText className="size-4 text-brand-500" />;
  return <FileIcon className="size-4 text-slate-400" />;
}

function Dropzone({ label, hint, dest, tone, onFiles, busy }:
  { label: string; hint: string; dest: string; tone: "c2" | "c3"; onFiles: (dest: string, f: File[]) => void; busy: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      role="button" tabIndex={0}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(dest, Array.from(e.dataTransfer.files)); }}
      className={clsx("flex cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed px-5 py-4 transition-all",
        busy && "pointer-events-none opacity-60",
        over ? (tone === "c2" ? "border-emerald-400 bg-emerald-50" : "border-rose-400 bg-rose-50")
          : "border-slate-200 hover:border-slate-300 hover:bg-slate-50")}>
      <div className={clsx("rounded-lg p-2", tone === "c2" ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-600")}>
        <UploadCloud className="size-5" />
      </div>
      <div>
        <p className="text-sm font-medium text-slate-900">{label}</p>
        <p className="text-xs text-slate-500">{hint}</p>
      </div>
      <input ref={input} type="file" multiple hidden onChange={(e) => { onFiles(dest, Array.from(e.target.files ?? [])); e.target.value = ""; }} />
    </div>
  );
}

function FileList({ files, level, onMove, onDelete }:
  { files: FileEntry[]; level: "C2" | "C3"; onMove: (f: FileEntry) => void; onDelete: (f: FileEntry) => void }) {
  if (!files.length) return <p className="py-6 text-center text-sm text-slate-400">Aucun fichier</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {files.map((f) => (
        <li key={f.path} className="group flex items-center gap-3 py-2.5">
          <div className="rounded-lg bg-slate-50 p-2 ring-1 ring-slate-100">{fileIcon(f.name)}</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-900" title={f.name}>{f.name}</p>
            <p className="truncate text-xs text-slate-500">{f.folder} · {formatSize(f.size)} · {f.mtime}</p>
          </div>
          <div className="flex shrink-0 gap-1 opacity-60 transition-opacity group-hover:opacity-100">
            <Button size="sm" variant="ghost" icon={<ArrowLeftRight className="size-3.5" />} onClick={() => onMove(f)}>
              {level === "C2" ? "Confidentiel" : "Travail"}
            </Button>
            <Button size="sm" variant="danger-ghost" icon={<Trash2 className="size-3.5" />} onClick={() => onDelete(f)} aria-label="Supprimer" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function TitleEditor({ code, refId, title }: { code: string; refId: string; title: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const qc = useQueryClient();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () => api.updateConsultation(code, refId, value),
    onSuccess: () => { qc.invalidateQueries(); setEditing(false); toast("Intitulé enregistré et masqué"); },
    onError: (e) => toast(e.message, "error"),
  });
  if (!editing) return (
    <button onClick={() => { setValue(title); setEditing(true); }} className="group inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900">
      {title || "Ajouter l'intitulé du marché"} <Pencil className="size-3.5 opacity-0 group-hover:opacity-100" />
    </button>
  );
  return (
    <form className="flex max-w-xl items-center gap-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <Input autoFocus value={value} onChange={(e) => setValue(e.target.value)} placeholder="Intitulé du marché (masqué : PII_PROJET_…)" />
      <Button type="submit" size="sm" variant="primary" loading={m.isPending}>Enregistrer</Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>Annuler</Button>
    </form>
  );
}

export default function Consultation() {
  const { code = "", ref = "" } = useParams();
  const key = ["consultation", code, ref];
  const { data, error, isLoading } = useQuery({ queryKey: key, queryFn: () => api.consultation(code, ref) });
  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status });
  const trusted = status?.provider.selected === "trusted";
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [copied, setCopied] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: key });

  const upload = useMutation({
    mutationFn: ({ dest, files }: { dest: string; files: File[] }) => api.upload(code, ref, dest, files),
    onSuccess: (r) => { refresh(); toast(`${r.saved.length} fichier(s) déposé(s)`); },
    onError: (e) => toast(e.message, "error"),
  });
  const onFiles = (dest: string, files: File[]) => files.length && upload.mutate({ dest, files });

  const move = async (f: FileEntry) => {
    const toC2 = f.level === "C3";
    if (toC2 && !(await confirm({ title: "Rendre ce fichier lisible par Claude ?", confirmLabel: "Passer en C2", tone: "primary",
      message: <>« {f.name} » passera en <strong>niveau C2</strong> : Claude pourra le lire, avec les données sensibles pseudonymisées.</> }))) return;
    try { await api.moveFile(code, ref, f.path, toC2 ? "travail" : "confidentiel"); refresh(); toast(toC2 ? "Fichier passé en C2" : "Fichier protégé (C3)"); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  const remove = async (f: FileEntry) => {
    if (!(await confirm({ title: "Supprimer ce fichier ?", confirmLabel: "Supprimer", message: <>« {f.name} » sera supprimé définitivement de votre poste.</> }))) return;
    try { await api.deleteFile(code, ref, f.path); refresh(); toast("Fichier supprimé"); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  const copy = async () => {
    if (!data) return;
    try { await navigator.clipboard.writeText(data.command); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { toast("Copie impossible : sélectionnez la commande à la main", "error"); }
  };

  if (isLoading) return <PageLoader />;
  if (error || !data) return <ErrorState error={error} />;
  const c2 = data.files.filter((f) => f.level === "C2");
  const c3 = data.files.filter((f) => f.level === "C3");

  return (
    <>
      <PageHeader
        breadcrumb={<Breadcrumb items={[{ label: "Clients", to: "/clients" }, { label: data.client.declared ? data.client.name : code, to: `/clients/${code}` }, { label: ref }]} />}
        title={<span className="font-mono">{ref}</span>}
        description={<TitleEditor code={code} refId={ref} title={data.consultation.title} />} />

      <div className="mb-6 overflow-hidden rounded-2xl bg-slate-950 shadow-lg ring-1 ring-slate-900">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-300"><Terminal className="size-4" /> Travailler avec Claude Code</div>
          <span className="text-xs text-slate-500">Terminal Ubuntu (WSL)</span>
        </div>
        <div className="flex items-center gap-3 px-5 py-4">
          <code className="flex-1 overflow-x-auto font-mono text-sm whitespace-nowrap text-emerald-300"><span className="text-slate-500 select-none">$ </span>{data.command}</code>
          <Button size="sm" variant={copied ? "secondary" : "primary"} icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />} onClick={copy}>
            {copied ? "Copié" : "Copier"}
          </Button>
        </div>
        <p className="px-5 pb-4 text-xs text-slate-500">Les PDF sont lus via pdftotext / OCR : client, montants, contacts et noms de personnes sont remplacés par des jetons avant envoi.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-t-4 border-t-emerald-500">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2"><ShieldCheck className="size-4 text-emerald-600" /><h2 className="text-[15px] font-semibold">Travail</h2><Badge tone="success">C2 · pseudonymisé</Badge></div>
              <p className="mt-1 text-sm text-slate-500">DCE, CCTP, mémoire technique, CV. Claude lit ces fichiers, données sensibles masquées.</p>
            </div>
          </div>
          <div className="space-y-2">
            <Dropzone label="Pièces du DCE" hint="Glissez ou cliquez · travail/DCE" dest="dce" tone="c2" onFiles={onFiles} busy={upload.isPending} />
            <Dropzone label="Mémoire technique, CV…" hint="travail/memoire-technique" dest="memoire" tone="c2" onFiles={onFiles} busy={upload.isPending} />
          </div>
          <div className="mt-4"><FileList files={c2} level="C2" onMove={move} onDelete={remove} /></div>
        </Card>

        <Card className="border-t-4 border-t-rose-500">
          <div className="mb-4">
            <div className="flex items-center gap-2"><Lock className="size-4 text-rose-600" /><h2 className="text-[15px] font-semibold">Confidentiel</h2>
              <Badge tone="danger">C3 · jamais envoyé à Anthropic</Badge></div>
            <p className="mt-1 text-sm text-slate-500">Offre de prix, BPU/DQE, NDA, stratégie commerciale, contenu technique stratégique.</p>
            <p className={clsx("mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium",
              trusted ? "bg-violet-50 text-violet-700" : "bg-slate-100 text-slate-600")}>
              <Lock className="size-3.5" />
              {trusted ? `${status?.provider.name} actif : lisible par Claude Code via ce fournisseur. La session sera marquée C3.`
                : "Claude actif : verrouillé. Basculez sur le fournisseur de confiance (Réglages) pour travailler sur ces fichiers."}
            </p>
          </div>
          <Dropzone label="Pièces confidentielles" hint="Glissez ou cliquez · _confidentiel" dest="confidentiel" tone="c3" onFiles={onFiles} busy={upload.isPending} />
          <div className="mt-4"><FileList files={c3} level="C3" onMove={move} onDelete={remove} /></div>
        </Card>
      </div>
    </>
  );
}
