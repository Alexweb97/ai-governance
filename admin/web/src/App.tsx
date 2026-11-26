import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api, setUnauthorizedHandler } from "./lib/api";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Clients from "./pages/Clients";
import ClientDetail from "./pages/ClientDetail";
import Consultation from "./pages/Consultation";
import Projects from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Simulator from "./pages/Simulator";
import Settings from "./pages/Settings";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { data, isLoading } = useQuery({ queryKey: ["session"], queryFn: api.session, staleTime: 60_000 });
  if (isLoading) return <div className="flex min-h-screen items-center justify-center"><Loader2 className="size-6 animate-spin text-slate-400" /></div>;
  if (!data?.authenticated) return <Navigate to="/connexion" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.setQueryData(["session"], { authenticated: false });
      navigate("/connexion", { replace: true, state: { from: location.pathname } });
    });
  }, [navigate, location.pathname, qc]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <UnauthorizedRedirect />
      <Routes>
        <Route path="/connexion" element={<Login />} />
        <Route element={<RequireAuth><Layout /></RequireAuth>}>
          <Route index element={<Dashboard />} />
          <Route path="clients" element={<Clients />} />
          <Route path="clients/:code" element={<ClientDetail />} />
          <Route path="clients/:code/:ref" element={<Consultation />} />
          <Route path="projets" element={<Projects />} />
          <Route path="projets/:id" element={<ProjectDetail />} />
          <Route path="simulateur" element={<Simulator />} />
          <Route path="reglages" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
