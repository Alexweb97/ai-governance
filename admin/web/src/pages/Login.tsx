import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Lock, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { Button, Field, Input } from "../components/ui";
import { LanguageSwitch, useI18n } from "../i18n";

export default function Login() {
  const { t, r } = useI18n();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.login(password);
      qc.setQueryData(["session"], { authenticated: true });
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login.error"));
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 px-4">
      <div className="absolute top-5 right-5"><LanguageSwitch dark /></div>
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[880px] -translate-x-1/2 rounded-full bg-brand-600/25 blur-3xl" />
      <div className="animate-pop-in relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 p-3 shadow-xl shadow-brand-900/50">
            <ShieldCheck className="size-7 text-white" />
          </div>
          <h1 className="text-xl font-semibold text-white">{t("login.title")}</h1>
          <p className="mt-1 text-sm text-slate-400">{t("login.subtitle")}</p>
        </div>
        <form onSubmit={submit} className="rounded-2xl bg-white p-6 shadow-2xl">
          <Field label={t("login.password")} error={error} hint={<>{r("login.hint")}</>}>
            <Input type="password" autoFocus required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
          <Button type="submit" variant="primary" loading={loading} icon={<Lock className="size-4" />} className="mt-5 w-full">
            {t("login.submit")}
          </Button>
        </form>
        <p className="mt-6 text-center text-xs text-slate-500">{t("login.localOnly")}</p>
      </div>
    </div>
  );
}
