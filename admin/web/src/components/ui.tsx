import {
  createContext, useContext, useEffect, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes,
} from "react";
import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import { useI18n } from "../i18n";

// ------------------------------------------------------------------ Button
type Variant = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white shadow-sm shadow-brand-600/20 hover:bg-brand-700 focus-visible:outline-brand-600",
  secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-200 shadow-xs hover:bg-slate-50 hover:text-slate-900",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
  danger: "bg-rose-600 text-white shadow-sm hover:bg-rose-700 focus-visible:outline-rose-600",
  "danger-ghost": "text-rose-600 hover:bg-rose-50",
};

export function Button({ variant = "secondary", size = "md", loading, icon, children, className, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-3.5 text-sm",
        variants[variant], className)}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Card
export function Card({ children, className, padded = true }: { children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={clsx("rounded-2xl border border-slate-200/80 bg-white shadow-xs", padded && "p-6", className)}>
      {children}
    </section>
  );
}

export function CardHeader({ title, description, action, icon }:
  { title: ReactNode; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 rounded-lg bg-slate-100 p-2 text-slate-600">{icon}</div>}
        <div>
          <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
          {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

// ------------------------------------------------------------------ Badge
type Tone = "neutral" | "brand" | "success" | "warning" | "danger";
const tones: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-100",
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200/70",
  warning: "bg-amber-50 text-amber-800 ring-amber-200/70",
  danger: "bg-rose-50 text-rose-700 ring-rose-200/70",
};
export function Badge({ tone = "neutral", children, dot, className }:
  { tone?: Tone; children: ReactNode; dot?: boolean; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", tones[tone], className)}>
      {dot && <span className={clsx("size-1.5 rounded-full", {
        "bg-slate-400": tone === "neutral", "bg-brand-500": tone === "brand", "bg-emerald-500": tone === "success",
        "bg-amber-500": tone === "warning", "bg-rose-500": tone === "danger" })} />}
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ Form fields
export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {error ? <span className="mt-1.5 block text-xs text-rose-600">{error}</span>
        : hint && <span className="mt-1.5 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

const fieldClass = "block w-full rounded-lg border-0 bg-white px-3 py-2 text-sm text-slate-900 shadow-xs ring-1 ring-inset ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 focus:outline-none";
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={clsx(fieldClass, "h-9", props.className)} />;
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={clsx(fieldClass, "resize-y", props.className)} />;
}

export function Alert({ tone = "danger", title, children, icon }:
  { tone?: "danger" | "warning" | "info"; title?: ReactNode; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className={clsx("flex gap-3 rounded-xl border p-4 text-sm", {
      "border-rose-200 bg-rose-50 text-rose-800": tone === "danger",
      "border-amber-200 bg-amber-50 text-amber-900": tone === "warning",
      "border-brand-100 bg-brand-50 text-brand-700": tone === "info" })}>
      {icon && <div className="mt-0.5 shrink-0">{icon}</div>}
      <div>{title && <p className="font-semibold">{title}</p>}{children && <div className={clsx(title && "mt-1")}>{children}</div>}</div>
    </div>
  );
}

// ------------------------------------------------------------------ Switch
export function Switch({ checked, onChange, disabled, label }:
  { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx("relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:opacity-50",
        checked ? "bg-brand-600" : "bg-slate-200")}>
      <span className={clsx("inline-block size-5 rounded-full bg-white shadow ring-0 transition-transform",
        checked ? "translate-x-[22px]" : "translate-x-0.5")} />
    </button>
  );
}

// ------------------------------------------------------------------ Tag input (variantes)
export function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const items = raw.split(/[\n;]/).map((s) => s.trim()).filter(Boolean);
    const next = [...value];
    for (const it of items) if (!next.some((v) => v.toLowerCase() === it.toLowerCase())) next.push(it);
    onChange(next);
    setDraft("");
  };
  return (
    <div className="flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-lg bg-white px-2 py-1.5 shadow-xs ring-1 ring-inset ring-slate-200 focus-within:ring-2 focus-within:ring-brand-500">
      {value.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded-md bg-slate-100 py-0.5 pr-1 pl-2 text-[13px] text-slate-700">
          {v}
          <button type="button" onClick={() => onChange(value.filter((x) => x !== v))}
            className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label={`Retirer ${v}`}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === ";") && draft.trim()) { e.preventDefault(); add(draft); }
          if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
        }}
        onBlur={() => draft.trim() && add(draft)}
        onPaste={(e) => { const t = e.clipboardData.getData("text"); if (/[\n;]/.test(t)) { e.preventDefault(); add(t); } }}
        placeholder={value.length ? "" : placeholder}
        className="min-w-[160px] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-slate-400"
      />
    </div>
  );
}

// ------------------------------------------------------------------ Modal
export function Modal({ open, onClose, title, description, children, footer, size = "md" }:
  { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children?: ReactNode; footer?: ReactNode; size?: "md" | "lg" }) {
  const ref = useRef<HTMLDivElement>(null);
  const { t } = useI18n();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, button[data-autofocus]")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 pt-[12vh]">
      <div className="animate-fade-in fixed inset-0 bg-slate-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div ref={ref} role="dialog" aria-modal="true"
        className={clsx("animate-pop-in relative w-full rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/5", size === "lg" ? "max-w-2xl" : "max-w-lg")}>
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{title}</h3>
            {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label={t("common.close")}>
            <X className="size-4" />
          </button>
        </div>
        {children && <div className="px-6 pt-5">{children}</div>}
        {footer && <div className="mt-6 flex justify-end gap-2 rounded-b-2xl border-t border-slate-100 bg-slate-50/60 px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Confirm dialog (remplace window.confirm)
type ConfirmOptions = { title: string; message: ReactNode; confirmLabel?: string; tone?: "danger" | "primary" };
const ConfirmContext = createContext<(o: ConfirmOptions) => Promise<boolean>>(async () => false);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [state, setState] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const close = (v: boolean) => { state?.resolve(v); setState(null); };
  const confirm = (o: ConfirmOptions) => new Promise<boolean>((resolve) => setState({ ...o, resolve }));
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Modal open={!!state} onClose={() => close(false)} title={state?.title}
        footer={<>
          <Button onClick={() => close(false)}>{t("common.cancel")}</Button>
          <Button data-autofocus variant={state?.tone === "primary" ? "primary" : "danger"} onClick={() => close(true)}>
            {state?.confirmLabel ?? t("common.confirm")}
          </Button>
        </>}>
        <div className="text-sm text-slate-600">{state?.message}</div>
      </Modal>
    </ConfirmContext.Provider>
  );
}
export const useConfirm = () => useContext(ConfirmContext);

// ------------------------------------------------------------------ divers
export function PageHeader({ title, description, actions, breadcrumb }:
  { title: ReactNode; description?: ReactNode; actions?: ReactNode; breadcrumb?: ReactNode }) {
  return (
    <div className="mb-8">
      {breadcrumb && <div className="mb-3">{breadcrumb}</div>}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
          {description && <p className="mt-1.5 max-w-3xl text-sm text-slate-500">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, description, action }:
  { icon: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-12 text-center">
      <div className="mb-3 rounded-xl bg-slate-100 p-3 text-slate-500">{icon}</div>
      <p className="text-sm font-medium text-slate-900">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-lg bg-slate-200/70", className)} />;
}

export function PageLoader() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96" />
      <div className="grid gap-4 pt-4 md:grid-cols-3"><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div>
      <Skeleton className="h-64" />
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const { t } = useI18n();
  return <Alert title={t("common.loadError")}>{error instanceof Error ? error.message : String(error)}</Alert>;
}
