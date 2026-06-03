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
  upload: (file: File, opts?: { folderId?: number | null; folderPath?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts?.folderId != null) fd.append("folder_id", String(opts.folderId));
    else if (opts?.folderPath) fd.append("folder_path", opts.folderPath);
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

// ── Folders / documents / atlas helpers ─────────────────────────
export const folders = {
  roots: (): Promise<{ folders: Folder[] }> => api.get("/folders?lazy=true"),
  children: (parentId: number): Promise<{ folders: Folder[] }> =>
    api.get(`/folders?lazy=true&parent_id=${parentId}`),
  documents: (folderId: number): Promise<{ documents: Doc[] }> =>
    api.get(`/folders/${folderId}/documents?limit=500`),
  create: (name: string, parentId?: number | null) =>
    api.post("/folders", { name, parent_id: parentId ?? null }),
  rename: (id: number, name: string) => api.patch(`/folders/${id}`, { name }),
  describe: (id: number, description: string) => api.patch(`/folders/${id}`, { description }),
  move: (id: number, newParentId: number | null) =>
    api.post(`/folders/${id}/move`, { new_parent_id: newParentId }),
  remove: (id: number) => api.del(`/folders/${id}`),
};

export const docs = {
  get: (id: number): Promise<Doc & { extract_confidence: number | null }> => api.get(`/documents/${id}`),
  content: (id: number): Promise<{ markdown: string }> => api.get(`/documents/${id}/content`),
  sections: (id: number, depth = 6): Promise<{ sections: Section[] }> =>
    api.get(`/documents/${id}/sections?depth=${depth}`),
  ingestMarkdown: (title: string, content: string, folderId?: number | null, folderPath?: string) =>
    api.post("/documents/markdown", { title, content, folder_id: folderId ?? null, folder_path: folderPath ?? null }),
  move: (id: number, folderId: number) => api.patch(`/documents/${id}`, { folder_id: folderId }),
  rename: (id: number, title: string) => api.patch(`/documents/${id}`, { title }),
  remove: (id: number) => api.del(`/documents/${id}`),
  downloadSource: (id: number, filename: string) => api.download(`/documents/${id}/source`, filename),
  unfiled: (): Promise<{ documents: Doc[] }> => api.get("/unfiled"),
};

export interface Job {
  id: number; status: string; stage: string; progress: number; document_id: number | null;
  faithfulness_score: number | null; tokens_in: number; tokens_out: number; attempts: number;
  error: string | null; created_at: string; updated_at: string;
  filename: string | null; pages_total: number | null; pages_done: number; source_key: string | null;
}
export const jobsApi = {
  list: (): Promise<{ jobs: Job[] }> => api.get("/jobs?limit=200"),
};

export interface AtlasNode {
  id: number; name: string; path: string; description: string; doc_count: number;
  documents: { id: number; title: string; status?: string }[]; children: AtlasNode[];
}
export const atlas = {
  tree: (): Promise<{ tree: AtlasNode[]; unfiled: { id: number; title: string }[] }> =>
    api.get("/atlas/tree"),
  markdown: (): Promise<{ markdown: string }> => api.get("/atlas"),
};

// ── Knowledge graph (derived) ───────────────────────────────────
export interface GraphEntity { id: number; name: string; kind: string; mention_count: number }
export interface EntityDetail {
  entity: GraphEntity;
  sections: { section_id: number; heading: string; document_id: number; doc_title: string }[];
  neighbors: { id: number; name: string; kind: string; weight: number }[];
}
export interface GraphData {
  nodes: { id: number; name: string; kind: string; mention_count: number }[];
  edges: { src: number; dst: number; weight: number }[];
}
export const graph = {
  overview: (limit = 80): Promise<GraphData> => api.get(`/graph?limit=${limit}`),
  entities: (q = ""): Promise<{ entities: GraphEntity[] }> => api.get(`/graph/entities${_q({ q, limit: "150" })}`),
  entity: (id: number): Promise<EntityDetail> => api.get(`/graph/entities/${id}`),
  rebuild: (): Promise<{ documents: number; entities: number }> => api.post("/graph/rebuild"),
};

// ── Agent memory (Markdown-native) ──────────────────────────────
export interface MemoryItem {
  id: number; agent_id: string; scope: string; tier: string; session_id: string;
  mkey: string; title: string; content: string; importance: number;
  access_count: number; created_at: string; last_accessed_at: string; score?: number;
}

function _q(params: Record<string, string>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const memory = {
  list: (tier = "", agentId = ""): Promise<{ memories: MemoryItem[] }> =>
    api.get(`/memory${_q({ tier, agent_id: agentId, limit: "200" })}`),
  recall: (q: string, agentId = ""): Promise<{ results: MemoryItem[] }> =>
    api.get(`/memory/recall${_q({ q, agent_id: agentId, top_k: "20" })}`),
  forget: (id: number) => api.del(`/memory/${id}`),
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
