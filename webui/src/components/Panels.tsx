import { useEffect, useState } from "react";
import { api, SearchHit } from "../lib/api";
import { Button, Input, Card, Pill } from "./ui";
import { Markdown } from "./Markdown";

export function SearchPanel({ onOpenSection }: { onOpenSection: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  async function run() {
    if (!q.trim()) return;
    setHits((await api.get(`/search?q=${encodeURIComponent(q)}&mode=${mode}&top_k=20`)).results);
  }
  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex gap-2 mb-4">
        <Input placeholder="Hybrid search…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
        <select className="input w-32" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="hybrid">hybrid</option><option value="bm25">bm25</option><option value="vector">vector</option>
        </select>
        <Button primary onClick={run}>Search</Button>
      </div>
      {hits && hits.length === 0 && <p className="muted">nothing found</p>}
      {(hits || []).map((h) => (
        <Card key={h.id} className="mb-2" onClick={() => onOpenSection(h.id)}>
          <div className="font-medium">{h.heading} <Pill>{h.score}</Pill></div>
          <div className="muted text-sm">{h.doc_title} · {h.breadcrumb}</div>
          <div className="text-sm mt-1">{(h.content || "").slice(0, 240)}…</div>
        </Card>
      ))}
    </div>
  );
}

export function AtlasPanel() {
  const [md, setMd] = useState("");
  useEffect(() => { api.get("/atlas").then((r) => setMd(r.markdown || "(empty)")); }, []);
  return <div className="flex-1 overflow-auto p-6"><h2 className="text-xl font-semibold mb-3">🗺 Atlas</h2><pre>{md}</pre></div>;
}

export function AdminPanel() {
  const [keys, setKeys] = useState<any[]>([]);
  const [hooks, setHooks] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [hookUrl, setHookUrl] = useState("");
  const [uEmail, setUEmail] = useState("");
  const [uPass, setUPass] = useState("");
  const [uRole, setURole] = useState("viewer");
  const [uErr, setUErr] = useState("");

  async function load() {
    try {
      setUsers((await api.get("/users")).users);
      setKeys((await api.get("/api-keys")).keys);
      setHooks((await api.get("/webhooks")).webhooks);
      setErr("");
    } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function createKey(scopes: string[]) {
    const r = await api.post("/api-keys", { scopes });
    setNewKey(r.api_key); load();
  }
  async function createHook() {
    if (!hookUrl) return;
    await api.post("/webhooks", { url: hookUrl, events: ["document.ready"], secret: "" });
    setHookUrl(""); load();
  }
  async function createUser() {
    setUErr("");
    try {
      await api.post("/users", { email: uEmail.trim(), password: uPass, role: uRole });
      setUEmail(""); setUPass(""); setURole("viewer"); load();
    } catch (e: any) { setUErr(e.message); }
  }
  async function changeRole(id: number, role: string) {
    try { await api.patch(`/users/${id}`, { role }); load(); } catch (e: any) { alert(e.message); }
  }
  async function toggleDisabled(id: number, disabled: boolean) {
    try { await api.patch(`/users/${id}`, { disabled }); load(); } catch (e: any) { alert(e.message); }
  }
  async function delUser(id: number) {
    if (!confirm("Delete user?")) return;
    try { await api.del(`/users/${id}`); load(); } catch (e: any) { alert(e.message); }
  }

  if (err) return <div className="flex-1 p-6"><Card className="border-yellow-600/60">Admin role required: {err}</Card></div>;
  return (
    <div className="flex-1 overflow-auto p-6 space-y-6">
      <section>
        <h2 className="text-lg font-semibold mb-2">Users</h2>
        <div className="flex gap-2 mb-2 flex-wrap items-center">
          <Input placeholder="email" value={uEmail} onChange={(e) => setUEmail(e.target.value)} />
          <Input type="password" placeholder="password (≥8)" value={uPass} onChange={(e) => setUPass(e.target.value)} />
          <select className="input w-28" value={uRole} onChange={(e) => setURole(e.target.value)}>
            <option value="viewer">viewer</option><option value="editor">editor</option><option value="admin">admin</option>
          </select>
          <Button primary onClick={createUser}>+ add</Button>
        </div>
        {uErr && <div className="text-red-400 text-sm mb-2">{uErr}</div>}
        {users.map((u) => (
          <div key={u.id} className="card mb-1 flex justify-between items-center text-sm">
            <span className={u.disabled ? "line-through text-mut" : ""}>#{u.id} {u.email}</span>
            <div className="flex gap-2 items-center">
              <select className="input w-24 py-0.5" value={u.role} onChange={(e) => changeRole(u.id, e.target.value)}>
                <option value="viewer">viewer</option><option value="editor">editor</option><option value="admin">admin</option>
              </select>
              <button className="text-acc" onClick={() => toggleDisabled(u.id, !u.disabled)}>{u.disabled ? "enable" : "disable"}</button>
              <button className="text-red-400" onClick={() => delUser(u.id)}>delete</button>
            </div>
          </div>
        ))}
      </section>
      <section>
        <h2 className="text-lg font-semibold mb-2">API keys</h2>
        <div className="flex gap-2 mb-2">
          <Button onClick={() => createKey(["read"])}>+ read</Button>
          <Button onClick={() => createKey(["read", "write"])}>+ read+write</Button>
          <Button onClick={() => createKey(["read", "write", "admin"])}>+ admin</Button>
        </div>
        {newKey && <Card className="mb-2 border-acc/60">New key (shown once): <code className="text-acc">{newKey}</code></Card>}
        {keys.map((k) => (
          <div key={k.id} className="card mb-1 flex justify-between text-sm">
            <span>#{k.id} {k.hint} · [{(k.scopes || []).join(", ")}]</span>
            <button className="text-red-400" onClick={async () => { await api.del(`/api-keys/${k.id}`); load(); }}>delete</button>
          </div>
        ))}
      </section>
      <section>
        <h2 className="text-lg font-semibold mb-2">Webhooks</h2>
        <div className="flex gap-2 mb-2">
          <Input placeholder="https://…/hook (event: document.ready)" value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} />
          <Button onClick={createHook}>+</Button>
        </div>
        {hooks.map((h) => (
          <div key={h.id} className="card mb-1 flex justify-between text-sm">
            <span>#{h.id} {h.url} · [{(h.events || []).join(", ")}]</span>
            <button className="text-red-400" onClick={async () => { await api.del(`/webhooks/${h.id}`); load(); }}>delete</button>
          </div>
        ))}
      </section>
    </div>
  );
}

export function SectionView({ id, onBack }: { id: number; onBack: () => void }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { api.get(`/sections/${id}`).then(setData); }, [id]);
  if (!data) return <div className="flex-1 p-6 muted">loading…</div>;
  return (
    <div className="flex-1 overflow-auto p-6">
      <Button onClick={onBack}>← back</Button>
      <h2 className="text-xl font-semibold my-3">{data.heading}</h2>
      <Markdown>{data.markdown}</Markdown>
    </div>
  );
}
