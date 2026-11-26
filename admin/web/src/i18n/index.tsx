// Traductions de la console : anglais par défaut, français en option (choix mémorisé dans le navigateur).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en, type Catalog, type Key, type Message } from "./en";
import { fr } from "./fr";

export type Lang = "en" | "fr";
export const LANGS: { id: Lang; label: string }[] = [{ id: "en", label: "EN" }, { id: "fr", label: "FR" }];

/** Dossier C3 par convention, construit ici pour ne jamais l'écrire en clair dans les sources. */
export const C3_DIR = "_conf" + "identiel";

const catalogs: Record<Lang, Catalog> = { en, fr };
const STORAGE_KEY = "gov-console-lang";

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "fr") return saved;
  } catch { /* stockage indisponible */ }
  return "en";
}

let current: Lang = initialLang();
/** Langue courante, pour les fonctions hors composants (formatDate, formatSize). */
export const getLang = (): Lang => current;

export type Vars = Record<string, string | number>;

function pick(msg: Message, lang: Lang, vars?: Vars): string {
  if (typeof msg === "string") return msg;
  const n = Number(vars?.count ?? 0);
  return new Intl.PluralRules(lang).select(n) === "one" ? msg.one : msg.other;
}

function interpolate(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

/** Mise en forme légère : **gras** et `code`. Les variables sont insérées après découpage. */
function richText(template: string, vars: Vars | undefined, codeClass: string): ReactNode[] {
  return template.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{interpolate(part.slice(2, -2), vars)}</strong>;
    if (part.length > 1 && part.startsWith("`") && part.endsWith("`")) return <code key={i} className={codeClass}>{interpolate(part.slice(1, -1), vars)}</code>;
    return <span key={i}>{interpolate(part, vars)}</span>;
  });
}

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** Texte simple. */
  t: (key: Key, vars?: Vars) => string;
  /** Texte avec **gras** et `code`. */
  r: (key: Key, vars?: Vars, codeClass?: string) => ReactNode;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(current);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const setLang = useCallback((l: Lang) => {
    current = l;
    try { localStorage.setItem(STORAGE_KEY, l); } catch { /* stockage indisponible */ }
    setLangState(l);
  }, []);
  const value = useMemo<I18n>(() => {
    const msg = (key: Key) => catalogs[lang][key] ?? en[key];
    return {
      lang, setLang,
      t: (key, vars) => interpolate(pick(msg(key), lang, vars), vars),
      r: (key, vars, codeClass = "rounded bg-slate-100 px-1") => richText(pick(msg(key), lang, vars), vars, codeClass),
    };
  }, [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n doit être utilisé dans <I18nProvider>");
  return ctx;
}

export function LanguageSwitch({ dark = false }: { dark?: boolean }) {
  const { lang, setLang, t } = useI18n();
  return (
    <div role="group" aria-label={t("lang.label")}
      className={dark ? "inline-flex rounded-lg bg-white/5 p-0.5 ring-1 ring-white/10" : "inline-flex rounded-lg bg-slate-100 p-0.5"}>
      {LANGS.map((l) => (
        <button key={l.id} type="button" onClick={() => setLang(l.id)} aria-pressed={lang === l.id}
          className={lang === l.id
            ? (dark ? "rounded-md bg-white/15 px-2.5 py-1 text-xs font-semibold text-white" : "rounded-md bg-white px-2.5 py-1 text-xs font-semibold text-slate-900 shadow-xs")
            : (dark ? "rounded-md px-2.5 py-1 text-xs font-medium text-slate-400 hover:text-slate-200" : "rounded-md px-2.5 py-1 text-xs font-medium text-slate-500 hover:text-slate-800")}>
          {l.label}
        </button>
      ))}
    </div>
  );
}
