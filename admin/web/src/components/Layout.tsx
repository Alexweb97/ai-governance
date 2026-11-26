import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, FolderGit2, FolderKanban, LayoutDashboard, LogOut, Settings2, ShieldCheck } from "lucide-react";
import clsx from "clsx";
import { api } from "../lib/api";
import { describeProvider } from "../lib/provider";
import { LanguageSwitch, useI18n } from "../i18n";
import type { Key } from "../i18n/en";

const nav: { to: string; label: Key; icon: typeof LayoutDashboard; end?: boolean }[] = [
  { to: "/", label: "nav.dashboard", icon: LayoutDashboard, end: true },
  { to: "/clients", label: "nav.clients", icon: FolderKanban },
  { to: "/projects", label: "nav.projects", icon: FolderGit2 },
  { to: "/simulator", label: "nav.simulator", icon: FlaskConical },
  { to: "/settings", label: "nav.settings", icon: Settings2 },
];

function HealthPill() {
  const { t } = useI18n();
  const { data } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15000 });
  const ok = data?.health.ok;
  return (
    <div className="flex items-center gap-2.5 rounded-xl bg-white/5 px-3 py-2.5 ring-1 ring-white/10">
      <span className="relative flex size-2.5">
        {ok && <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
        <span className={clsx("relative inline-flex size-2.5 rounded-full", data === undefined ? "bg-slate-500" : ok ? "bg-emerald-400" : "bg-rose-500")} />
      </span>
      <div className="min-w-0 leading-tight">
        <p className="text-xs font-medium text-white">{data === undefined ? t("health.checking") : ok ? t("health.active") : t("health.down")}</p>
        <p className="truncate text-[11px] text-slate-400">
          {data ? t("health.summary", {
            provider: describeProvider(data.provider.selected, data.provider, t).name,
            count: data.health.terms ?? 0,
            ner: data.health.presidio === "ok" ? t("health.nerOn") : t("health.nerOff"),
          }) : "—"}
        </p>
      </div>
    </div>
  );
}

export default function Layout() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const logout = async () => {
    await api.logout().catch(() => {});
    qc.clear();
    qc.setQueryData(["session"], { authenticated: false });
    navigate("/login");
  };
  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col bg-slate-950 px-4 py-5">
        <div className="mb-8 flex items-center gap-3 px-2">
          <div className="rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 p-2 shadow-lg shadow-brand-900/40">
            <ShieldCheck className="size-5 text-white" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">{t("brand.title")}</p>
            <p className="text-xs text-slate-400">Claude Code</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => clsx(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-200")}>
              <Icon className="size-4 shrink-0" />
              {t(label)}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-3">
          <HealthPill />
          <div className="flex items-center justify-between gap-2">
            <button onClick={logout}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-400 transition-colors hover:bg-white/5 hover:text-slate-200">
              <LogOut className="size-4" /> {t("layout.logout")}
            </button>
            <LanguageSwitch dark />
          </div>
        </div>
      </aside>
      <main className="ml-64 flex-1">
        <div className="mx-auto max-w-6xl px-10 py-10 animate-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
