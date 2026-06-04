// Administration: Users (roles, enable/disable, password reset, delete), API keys
// (pick scopes → Create), Webhooks (events + secret + send-test), audit Logs, and a rich
// Health dashboard.
import { useEffect, useState } from "react";
import {
  Users, KeyRound, Webhook, Trash2, Copy, ShieldAlert, Activity, ScrollText,
} from "lucide-react";
import { api, admin, User } from "../lib/api";
import { Button, Input, Card, Pill, Tabs, EmptyState, Spinner, Modal, toast } from "./ui";

export function AdminPanel() {
  const [tab, setTab] = useState("users");
  const [forbidden, setForbidden] = useState(false);
  useEffect(() => { api.get("/users").catch((e) => { if (e.status === 403) setForbidden(true); }); }, []);
  if (forbidden) return <div className="flex-1 p-6"><EmptyState icon={<ShieldAlert className="w-10 h-10" />} title="Admin only" hint="Your role doesn't include admin permissions." /></div>;

  const I = (C: any) => <C className="w-4 h-4" />;
  return (
    <div className="flex-1 overflow-auto p-6">
      <h2 className="text-xl font-semibold mb-3">Administration</h2>
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: "users", label: <span className="flex items-center gap-1.5">{I(Users)} Users</span> },
        { id: "keys", label: <span className="flex items-center gap-1.5">{I(KeyRound)} API keys</span> },
        { id: "hooks", label: <span className="flex items-center gap-1.5">{I(Webhook)} Webhooks</span> },
        { id: "logs", label: <span className="flex items-center gap-1.5">{I(ScrollText)} Logs</span> },
        { id: "health", label: <span className="flex items-center gap-1.5">{I(Activity)} Health</span> },
      ]} />
      {tab === "users" && <UsersTab />}
      {tab === "keys" && <KeysTab />}
      {tab === "hooks" && <HooksTab />}
      {tab === "logs" && <LogsTab />}
      {tab === "health" && <HealthTab />}
    </div>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [email, setEmail] = useState(""); const [pass, setPass] = useState(""); const [role, setRole] = useState("viewer");
  const [pwUser, setPwUser] = useState<User | null>(null); const [pw, setPw] = useState("");
  const load = () => api.get("/users").then((r) => setUsers(r.users)).catch((e) => toast(e.message, "err"));
  useEffect(() => { load(); }, []);

  async function add() {
    if (!email.trim() || pass.length < 8) { toast("Email + password (≥8 chars) required", "err"); return; }
    try { await api.post("/users", { email: email.trim(), password: pass, role }); setEmail(""); setPass(""); setRole("viewer"); load(); toast("User created"); }
    catch (e: any) { toast(e.message, "err"); }
  }
  const act = (fn: Promise<any>) => fn.then(load).then(() => toast("Updated")).catch((e: any) => toast(e.message, "err"));
  async function setPassword() {
    if (pw.length < 8) { toast("Password must be ≥8 chars", "err"); return; }
    try { await api.patch(`/users/${pwUser!.id}`, { password: pw }); setPwUser(null); setPw(""); toast("Password updated — user's sessions were revoked"); }
    catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <div>
      <Card className="mb-4">
        <div className="text-sm font-medium mb-2">Add a user</div>
        <div className="flex gap-2 flex-wrap items-center">
          <Input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} className="flex-1 min-w-[180px]" />
          <Input type="password" placeholder="password (≥8)" value={pass} onChange={(e) => setPass(e.target.value)} className="w-40" />
          <select className="input w-28" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="viewer">viewer</option><option value="editor">editor</option><option value="admin">admin</option>
          </select>
          <Button primary onClick={add}>Add user</Button>
        </div>
      </Card>
      {users === null ? <Spinner /> : users.length === 0 ? <EmptyState title="No users" /> : (
        <table className="w-full text-sm">
          <thead className="text-mut text-left border-b border-line"><tr>
            <th className="py-2">Email</th><th>Role</th><th>Status</th><th>Last login</th><th className="text-right">Actions</th>
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-line/50">
                <td className={`py-2 ${u.disabled ? "line-through text-mut" : ""}`}>{u.email}</td>
                <td>
                  <select className="input py-0.5 w-24" value={u.role} onChange={(e) => act(api.patch(`/users/${u.id}`, { role: e.target.value }))}>
                    <option value="viewer">viewer</option><option value="editor">editor</option><option value="admin">admin</option>
                  </select>
                </td>
                <td>{u.disabled ? <Pill>disabled</Pill> : <Pill>active</Pill>}</td>
                <td className="muted">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}</td>
                <td className="text-right whitespace-nowrap">
                  <button className="text-acc mr-3" title="Set / reset password" onClick={() => { setPwUser(u); setPw(""); }}>set password</button>
                  <button className="text-acc mr-3" onClick={() => act(api.patch(`/users/${u.id}`, { disabled: !u.disabled }))}>{u.disabled ? "enable" : "disable"}</button>
                  <button className="text-red-400" onClick={() => { if (confirm(`Delete ${u.email}?`)) act(api.del(`/users/${u.id}`)); }}><Trash2 className="w-4 h-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Modal open={!!pwUser} onClose={() => setPwUser(null)} title={`Set password — ${pwUser?.email || ""}`}>
        <div className="text-sm muted mb-2">Sets a new password as admin. The user's active sessions are revoked.</div>
        <Input type="password" placeholder="new password (≥8 chars)" value={pw} onChange={(e) => setPw(e.target.value)} className="w-full mb-3" autoFocus />
        <div className="flex gap-2 justify-end"><Button onClick={() => setPwUser(null)}>Cancel</Button><Button primary onClick={setPassword}>Set password</Button></div>
      </Modal>
    </div>
  );
}

const SCOPES = ["read", "write", "admin"] as const;

function KeysTab() {
  const [keys, setKeys] = useState<any[] | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set(["read"]));
  const load = () => api.get("/api-keys").then((r) => setKeys(r.keys)).catch((e) => toast(e.message, "err"));
  useEffect(() => { load(); }, []);
  function toggle(s: string) { setPicked((p) => { const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n; }); }
  async function create() {
    if (picked.size === 0) { toast("Select at least one scope", "err"); return; }
    try { const r = await api.post("/api-keys", { scopes: [...picked] }); setFresh(r.api_key); load(); toast("Key created"); }
    catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <div>
      <Card className="mb-4">
        <div className="text-sm font-medium mb-2">Create a service key</div>
        <div className="flex gap-4 items-center mb-3">
          {SCOPES.map((s) => (
            <label key={s} className="flex items-center gap-1.5 cursor-pointer text-sm">
              <input type="checkbox" checked={picked.has(s)} onChange={() => toggle(s)} /> {s}
            </label>
          ))}
          <Button primary onClick={create}>Create key</Button>
        </div>
        {fresh && (
          <div className="flex items-center gap-2 bg-[#0b0e12] border border-acc/60 rounded p-2">
            <KeyRound className="w-4 h-4 text-acc shrink-0" />
            <code className="text-acc text-sm break-all flex-1">{fresh}</code>
            <button className="text-mut hover:text-fg" title="Copy" onClick={() => { navigator.clipboard.writeText(fresh); toast("Copied"); }}><Copy className="w-4 h-4" /></button>
            <button className="text-mut hover:text-fg" onClick={() => setFresh(null)}>✕</button>
          </div>
        )}
        {fresh && <div className="muted text-xs mt-1">Shown once — store it now.</div>}
      </Card>
      {keys === null ? <Spinner /> : keys.length === 0 ? <EmptyState title="No API keys" /> : (
        <table className="w-full text-sm">
          <thead className="text-mut text-left border-b border-line"><tr><th className="py-2">Key</th><th>Scopes</th><th>Last used</th><th></th></tr></thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id} className="border-b border-line/50">
                <td className="py-2 font-mono">{k.hint}</td>
                <td>{(k.scopes || []).map((s: string) => <Pill key={s}>{s}</Pill>)}</td>
                <td className="muted">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                <td className="text-right"><button className="text-red-400" onClick={async () => { if (confirm("Revoke key?")) { await api.del(`/api-keys/${k.id}`); load(); toast("Key revoked"); } }}><Trash2 className="w-4 h-4 inline" /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function HooksTab() {
  const [hooks, setHooks] = useState<any[] | null>(null);
  const [events, setEvents] = useState<string[]>([]);
  const [url, setUrl] = useState(""); const [secret, setSecret] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  async function load() {
    try { const r = await admin.webhooks(); setHooks(r.webhooks); setEvents(r.available_events); if (!picked.size && r.available_events.length) setPicked(new Set([r.available_events[0]])); }
    catch (e: any) { toast(e.message, "err"); }
  }
  useEffect(() => { load(); }, []);
  function toggle(ev: string) { setPicked((p) => { const n = new Set(p); n.has(ev) ? n.delete(ev) : n.add(ev); return n; }); }
  async function create() {
    if (!/^https?:\/\//.test(url)) { toast("Enter a valid http(s) URL", "err"); return; }
    if (picked.size === 0) { toast("Select at least one event", "err"); return; }
    try { await api.post("/webhooks", { url, events: [...picked], secret }); setUrl(""); setSecret(""); load(); toast("Webhook added"); }
    catch (e: any) { toast(e.message, "err"); }
  }
  async function test(id: number) {
    try { const r = await admin.webhookTest(id); toast(r.ok ? `Test delivered (HTTP ${r.status_code})` : `Endpoint returned ${r.status_code}`, r.ok ? "ok" : "err"); }
    catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <div>
      <Card className="mb-4">
        <div className="text-sm font-medium mb-2">Add a webhook</div>
        <div className="flex gap-2 flex-wrap items-center mb-2">
          <Input placeholder="https://example.com/hook" value={url} onChange={(e) => setUrl(e.target.value)} className="flex-1 min-w-[220px]" />
          <Input type="password" placeholder="signing secret (optional)" value={secret} onChange={(e) => setSecret(e.target.value)} className="w-52" />
          <Button primary onClick={create}>Add</Button>
        </div>
        <div className="flex gap-3 text-sm flex-wrap">
          <span className="muted">Events:</span>
          {events.map((ev) => (
            <label key={ev} className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={picked.has(ev)} onChange={() => toggle(ev)} /> {ev}
            </label>
          ))}
        </div>
        <div className="muted text-xs mt-2">Deliveries are POSTed as JSON, HMAC-signed (X-Tome-Signature) and SSRF-guarded. Use “Send test” to verify your endpoint.</div>
      </Card>
      {hooks === null ? <Spinner /> : hooks.length === 0 ? <EmptyState title="No webhooks" /> : (
        <table className="w-full text-sm">
          <thead className="text-mut text-left border-b border-line"><tr><th className="py-2">URL</th><th>Events</th><th className="text-right">Actions</th></tr></thead>
          <tbody>
            {hooks.map((h) => (
              <tr key={h.id} className="border-b border-line/50">
                <td className="py-2 break-all">{h.url}</td>
                <td>{(h.events || []).map((e: string) => <Pill key={e}>{e}</Pill>)}</td>
                <td className="text-right whitespace-nowrap">
                  <button className="text-acc mr-3" onClick={() => test(h.id)}>send test</button>
                  <button className="text-red-400" onClick={async () => { if (confirm("Delete webhook?")) { await api.del(`/webhooks/${h.id}`); load(); toast("Deleted"); } }}><Trash2 className="w-4 h-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function LogsTab() {
  const [events, setEvents] = useState<any[] | null>(null);
  useEffect(() => { admin.audit().then((r) => setEvents(r.events)).catch((e) => toast(e.message, "err")); }, []);
  if (events === null) return <Spinner />;
  if (!events.length) return <EmptyState icon={<ScrollText className="w-10 h-10" />} title="No audit events yet" hint="Logins, user/key/webhook changes will appear here." />;
  return (
    <table className="w-full text-sm">
      <thead className="text-mut text-left border-b border-line"><tr><th className="py-2">When</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead>
      <tbody>
        {events.map((e) => (
          <tr key={e.id} className="border-b border-line/50">
            <td className="py-2 muted whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</td>
            <td>{e.actor}</td>
            <td><Pill>{e.action}</Pill></td>
            <td className="muted break-words">{e.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HealthTab() {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => { admin.stats().then(setS).catch((e) => setErr(e.message)); }, []);
  if (err) return <div className="text-red-400 text-sm">{err}</div>;
  if (!s) return <Spinner />;
  const stat = (label: string, val: any) => (
    <Card className="text-center"><div className="text-2xl font-semibold">{val}</div><div className="muted text-xs mt-1">{label}</div></Card>
  );
  const num = (n: number) => (n ?? 0).toLocaleString();
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {stat("Documents", num(s.documents))}
        {stat("Folders", num(s.folders))}
        {stat("Sections", num(s.sections))}
        {stat("Retrieval chunks", num(s.retrieval_chunks))}
        {stat("Graph entities", num(s.graph_entities))}
        {stat("Memories", num(s.memories))}
        {stat("Users", num(s.users))}
        {stat("API keys / webhooks", `${num(s.api_keys)} / ${num(s.webhooks)}`)}
        {stat("Total characters", num(s.total_chars))}
        {stat("Tokens in", num(s.tokens_in))}
        {stat("Tokens out", num(s.tokens_out))}
        {stat("pgvector", s.pgvector ? "on" : "off")}
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2">Processing jobs</h3>
        <div className="flex flex-wrap gap-2">
          {Object.keys(s.jobs || {}).length === 0 ? <span className="muted text-sm">no jobs</span>
            : Object.entries(s.jobs).map(([k, v]) => <Pill key={k}>{k}: {String(v)}</Pill>)}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2">Avg ingest time per stage
          {s.avg_stage_ms_sampled ? <span className="muted font-normal"> · last {s.avg_stage_ms_sampled} docs</span> : null}</h3>
        <div className="flex flex-wrap gap-2">
          {s.avg_stage_ms && Object.keys(s.avg_stage_ms).length ?
            Object.entries(s.avg_stage_ms).map(([k, v]) => (
              <Pill key={k}>{k}: {Number(v) >= 1000 ? `${(Number(v) / 1000).toFixed(1)}s` : `${v}ms`}</Pill>
            )) : <span className="muted text-sm">no timing data yet</span>}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2">Configuration</h3>
        <div className="flex flex-wrap gap-2">
          {s.config && Object.entries(s.config).map(([k, v]) => (
            <Pill key={k}>{k}: {typeof v === "boolean" ? (v ? "on" : "off") : String(v)}</Pill>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2">Quality (corpus faithfulness)</h3>
        {s.faithfulness && Object.keys(s.faithfulness).length ? (
          <div className="flex flex-wrap gap-2">
            {Object.entries(s.faithfulness).map(([k, v]) => (
              <Pill key={k}>{k}: {typeof v === "number" ? (v as number).toFixed(3) : String(v)}</Pill>
            ))}
          </div>
        ) : <span className="muted text-sm">no eval data yet</span>}
      </div>
    </div>
  );
}
