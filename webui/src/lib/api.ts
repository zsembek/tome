// Tome API client. The session token is stored in localStorage and sent as a Bearer header.
const TOKEN_KEY = "tome_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t: string) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  const t = getToken();
  if (t) h["Authorization"] = `Bearer ${t}`;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

async function handle(r: Response) {
  if (r.status === 401) throw new ApiError(401, "Sign-in required");
  if (r.status === 403) throw new ApiError(403, "Insufficient permissions (role)");
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new ApiError(r.status, String(detail));
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("application/json") ? r.json() : r.text();
}

export class ApiError extends Error {
  constructor(public status: number, msg: string) { super(msg); }
}

export const api = {
  get: (p: string) => fetch(`/v1${p}`, { headers: headers(false) }).then(handle),
  post: (p: string, body?: any) =>
    fetch(`/v1${p}`, { method: "POST", headers: headers(), body: JSON.stringify(body ?? {}) }).then(handle),
  patch: (p: string, body?: any) =>
    fetch(`/v1${p}`, { method: "PATCH", headers: headers(), body: JSON.stringify(body ?? {}) }).then(handle),
  del: (p: string) => fetch(`/v1${p}`, { method: "DELETE", headers: headers(false) }).then(handle),
  upload: (file: File, folderPath?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (folderPath) fd.append("folder_path", folderPath);
    else fd.append("auto_file", "true");
    const h: Record<string, string> = {};
    const t = getToken();
    if (t) h["Authorization"] = `Bearer ${t}`;
    return fetch("/v1/documents", { method: "POST", headers: h, body: fd }).then(handle);
  },
  download: async (p: string, filename: string) => {
    // Download via fetch + blob using the Authorization header (token never in the URL).
    const r = await fetch(`/v1${p}`, { headers: headers(false) });
    if (!r.ok) throw new ApiError(r.status, "download failed");
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  },
};

// ── Authentication ──────────────────────────────────────────────
export interface AuthStatus { open_mode: boolean; needs_bootstrap: boolean; master_key_enabled: boolean; }
export interface Me { email: string | null; role: string; scopes: string[]; via: string; }

export const auth = {
  status: (): Promise<AuthStatus> => api.get("/auth/status"),
  me: (): Promise<Me> => api.get("/auth/me"),
  async login(email: string, password: string) {
    const r = await api.post("/auth/login", { email, password });
    setToken(r.token); return r.user;
  },
  async bootstrap(email: string, password: string) {
    const r = await api.post("/auth/bootstrap", { email, password });
    setToken(r.token); return r.user;
  },
  async logout() {
    try { await api.post("/auth/logout"); } catch {}
    setToken("");
  },
};

// ── Short-lived signed image URLs (instead of putting the token in the URL) ──
const ASSET_RE = /\/v1\/assets\/[^\s)"']+/g;

export async function signAssetUrls(md: string): Promise<string> {
  if (!md || !md.includes("/v1/assets/")) return md;
  const keys = new Set<string>();
  for (const m of md.matchAll(ASSET_RE)) {
    keys.add(m[0].replace(/^\/v1\/assets\//, "").split("?")[0]);
  }
  if (keys.size === 0) return md;
  try {
    const r = await api.post("/assets/sign", { keys: Array.from(keys), ttl: 600 });
    const signed: Record<string, string> = r.signed || {};
    return md.replace(ASSET_RE, (u) => {
      const key = u.replace(/^\/v1\/assets\//, "").split("?")[0];
      return signed[key] || u;
    });
  } catch {
    return md;
  }
}

// types
export interface Folder { id: number; parent_id: number | null; path: string; name: string; description: string; doc_count: number; has_children?: boolean; }
export interface Doc { id: number; folder_id: number; title: string; summary: string; tags: string[]; parts: number; section_count: number; faithfulness_score: number | null; status: string; }
export interface Section { id: number; parent_id: number | null; order_index: number; level: number; heading: string; breadcrumb: string; char_count: number; }
export interface SearchHit { id: number; heading: string; breadcrumb: string; content: string; doc_title: string; score: number; }
export interface User { id: number; email: string; role: string; disabled: boolean; created_at: string; last_login_at: string | null; }
