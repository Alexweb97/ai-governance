// Accès à l'API de la console. Cookie de session (même origine) + en-tête anti-CSRF.
import { getLang } from "../i18n";

export type Level = "C2" | "C3";

export interface Consultation { ref: string; title: string; has_confidential: boolean }
export interface Client {
  code: string; name: string; variants: string[]; declared: boolean;
  consultations: Consultation[]; created?: string; updated?: string;
}
export interface FileEntry { path: string; name: string; folder: string; level: Level; size: number; mtime: string }
export interface ConsultationDetail {
  client: { code: string; name: string; declared: boolean };
  consultation: Consultation;
  files: FileEntry[];
  command: string;
  destinations: Record<string, string>;
}
export type Decision = "ask" | "deny";
export interface Settings {
  mask_amounts: boolean; allow_images: boolean; ner_documents: boolean; ner_tool_results: boolean;
  ner_threshold: number;
  mask_types: Record<string, boolean>;
  allowlist_extra: string[];
  decisions: Record<string, Decision>;
  pii_tables: string[];
  web_deny_domains_extra: string[];
}
export type BoolSettingKey = "mask_amounts" | "allow_images" | "ner_documents" | "ner_tool_results";
export type Labels = Record<string, { title: string; help: string }>;
export interface SettingChange { key: string; sub: string | null; old: unknown; new: unknown; reduces: boolean }
export interface SettingsHistoryEntry { ts: string; action: "update" | "reset"; changes: SettingChange[]; reduces: boolean }
export interface SettingsResponse {
  settings: Settings; defaults: Settings; locked: { allowlist: string[]; web_deny_domains: string[] };
  labels: Labels; type_labels: Labels; decision_labels: Labels; history: SettingsHistoryEntry[]; policy_loaded: boolean;
}
export interface GovEvent {
  ts: string; kind: "deny" | "ask" | "pseudo" | "config" | "c3"; label: string; tool: string;
  rule: string; details: string; counts: Record<string, number>; model: string; provider: string;
}
export type ProviderId = "claude" | "trusted";
export interface C3Session { id: string; short: string; cwd: string; opened: string; last: string; ended: string | null; accesses: number; open: boolean }
export interface ProviderInfo {
  name: string; vendor: string; detail: string; hosting: string;
  model?: string; host?: string; custom_name?: boolean;  // fournisseur de confiance
}
export interface Status {
  health: { ok: boolean; proxy?: string; presidio?: string | null; redis?: string | null; terms?: number; error?: string;
    provider?: ProviderId; trusted?: "ok" | "not_configured" | "key_missing" | "auth_error" | "down" | null };
  provider: ProviderInfo & { selected: ProviderId; active?: ProviderId };
  clients: { declared: number; undeclared: string[]; consultations: number };
  events: GovEvent[];
  grafana_url: string;
}
export interface Preview { text: string; detections: { type: string; source: string }[] }

// Projets de code
export type C3Source = "declared" | "inherited" | "marker" | null;
export interface Project {
  id: string; name: string; path: string; host_path: string; client: string; client_name: string;
  mask_name: boolean; c3: string[]; exists: boolean; created?: string; updated?: string;
}
export interface ProjectDetail extends Project { command: string }
export interface ProjectCandidate { path: string; host_path: string; git: boolean; declared: boolean; depth: number }
export interface TreeEntry { name: string; path: string; dir: boolean; size: number; mtime: string; c3: C3Source; contains_c3: boolean }
export interface ScanHit { path: string; c3: C3Source }
export interface ScanResult {
  terms: { term: string; kind: string; files: number; samples: ScanHit[] }[];
  secret_files: ScanHit[];
  credentials: (ScanHit & { line: number; key: string })[];
  path_terms: string[];
  stats: { files: number; read: number; skipped_large: number; skipped_binary: number; truncated: boolean };
}
export interface ProjectInput { name: string; client: string; mask_name: boolean }

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Gov-Admin": "1" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  let data: any = {};
  try { data = await r.json(); } catch { /* réponse vide */ }
  if (r.status === 401 && !url.endsWith("/api/session")) onUnauthorized();
  if (!r.ok) throw new ApiError(data.error || data.detail || `Erreur ${r.status}`, r.status);
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  session: () => request<{ authenticated: boolean }>("GET", "/api/session"),
  login: (password: string) => request<{ authenticated: boolean }>("POST", "/api/session", { password }),
  logout: () => request<{ authenticated: boolean }>("DELETE", "/api/session"),

  clients: () => request<{ clients: Client[]; next_code: string }>("GET", "/api/clients"),
  client: (code: string) => request<Client>("GET", `/api/clients/${enc(code)}`),
  createClient: (b: { code: string; name: string; variants: string[] }) =>
    request<{ code: string }>("POST", "/api/clients", b),
  updateClient: (code: string, b: { name: string; variants: string[] }) =>
    request("PUT", `/api/clients/${enc(code)}`, b),
  deleteClient: (code: string) => request("DELETE", `/api/clients/${enc(code)}`),

  consultation: (code: string, ref: string) =>
    request<ConsultationDetail>("GET", `/api/clients/${enc(code)}/${enc(ref)}`),
  createConsultation: (code: string, b: { ref: string; title: string }) =>
    request<{ ref: string }>("POST", `/api/clients/${enc(code)}/consultations`, b),
  updateConsultation: (code: string, ref: string, title: string) =>
    request("PUT", `/api/clients/${enc(code)}/${enc(ref)}`, { title }),
  upload: (code: string, ref: string, dest: string, files: File[]) => {
    const fd = new FormData();
    fd.append("dest", dest);
    files.forEach((f) => fd.append("files", f, f.name));
    return request<{ saved: string[] }>("POST", `/api/clients/${enc(code)}/${enc(ref)}/files`, fd);
  },
  moveFile: (code: string, ref: string, path: string, dest: string) =>
    request("POST", `/api/clients/${enc(code)}/${enc(ref)}/files/move`, { path, dest }),
  deleteFile: (code: string, ref: string, path: string) =>
    request("POST", `/api/clients/${enc(code)}/${enc(ref)}/files/delete`, { path }),

  projects: () => request<{ projects: Project[]; root: string; mounted: boolean }>("GET", "/api/projects"),
  projectCandidates: () => request<{ candidates: ProjectCandidate[]; root: string }>("GET", "/api/projects/candidates"),
  project: (id: string) => request<ProjectDetail>("GET", `/api/projects/${enc(id)}`),
  createProject: (b: ProjectInput & { path: string }) => request<{ id: string }>("POST", "/api/projects", b),
  updateProject: (id: string, b: ProjectInput) => request("PUT", `/api/projects/${enc(id)}`, b),
  deleteProject: (id: string) => request("DELETE", `/api/projects/${enc(id)}`),
  projectTree: (id: string, path: string) =>
    request<{ path: string; entries: TreeEntry[] }>("GET", `/api/projects/${enc(id)}/tree?path=${enc(path)}`),
  setC3: (id: string, path: string, c3: boolean) => request<{ c3: string[] }>("POST", `/api/projects/${enc(id)}/c3`, { path, c3 }),
  scanProject: (id: string) => request<ScanResult>("POST", `/api/projects/${enc(id)}/scan`),

  settings: () => request<SettingsResponse>("GET", "/api/settings"),
  updateSettings: (b: Partial<Settings>) => request<{ settings: Settings }>("PUT", "/api/settings", b),
  resetSettings: () => request<{ settings: Settings }>("POST", "/api/settings/reset"),

  status: () => request<Status>("GET", "/api/status"),
  provider: () => request<{ provider: ProviderId; providers: Record<ProviderId, ProviderInfo> }>("GET", "/api/provider"),
  c3Sessions: () => request<{ sessions: C3Session[] }>("GET", "/api/c3-sessions"),
  closeC3Session: (id: string) => request("POST", `/api/c3-sessions/${enc(id)}/close`),
  setProvider: (provider: ProviderId) => request<{ provider: ProviderId }>("PUT", "/api/provider", { provider }),
  preview: (text: string, scope: "user_text" | "document") => request<Preview>("POST", "/api/preview", { text, scope }),
};

export function formatSize(bytes: number): string {
  const fr = getLang() === "fr";
  if (bytes < 1024) return `${bytes} ${fr ? "o" : "B"}`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} ${fr ? "Ko" : "KB"}`;
  return `${(bytes / 1024 / 1024).toFixed(1)} ${fr ? "Mo" : "MB"}`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(getLang() === "fr" ? "fr-FR" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
