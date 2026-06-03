// Admin: users / API keys / webhooks — tabbed, table-based, with validation + toasts.
import { useEffect, useState } from "react";
import { Users, KeyRound, Webhook, Trash2, Copy, ShieldAlert, Activity } from "lucide-react";
import { api, User } from "../lib/api";
import { Button, Input, Card, Pill, Tabs, EmptyState, Spinner, toast } from "./ui";

export function AdminPanel() {
  const [tab, setTab] = useState("users");
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => { api.get("/users").catch((e) => { if (e.status === 403) setForbidden(true); }); }, []);
  if (forbidden) return <div className="flex-1 p-6"><EmptyState icon={<ShieldAlert className="w-10 h-10" />} title="Admin only" hint="Your role doesn't include admin permissions." /></div>;

  return (
    <div className="flex-1 overflow-auto p-6">
      <h2 className="text-xl font-semibold mb-3">Administration</h2>
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: "users", label: <span className="flex items-center gap-1.5"><Users className="w-4 h-4" /> Users</span> },
        { id: "keys", label: <span className="flex items-center gap-1.5"><KeyRound className="w-4 h-4" /> API keys</span> },
        { id: "hooks", label: <span className="flex items-center gap-1.5"><Webhook className="w-4 h-4" /> Webhooks</span> },
        { id: "health", label: <span className="flex items-center gap-1.5"><Activity className="w-4 h-4" /> Health</span> },
      ]} />
      {tab === "users" && <UsersTab />}
      {tab === "keys" && <KeysTab />}
      {tab === "hooks" && <HooksTab />}
      {tab === "health" && <HealthTab />}
    </div>
  );
}

function HealthTab() {
  const [usage, setUsage] = useState<any>(null);
  const [evalm, setEvalm] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/usage").then(setUsage).catch((e) => setErr(e.message));
    api.get("/eval").then(setEvalm).catch(() => {});
  }, []);
  if (err) return <div className="text-red-400 text-sm">{err}</div>;
  if (!usage) return <Spinner />;
  const stat = (label: string, val: any) => (
    <Card className="text-center"><div className="text-2xl font-semibold">{val}</div><div className="muted text-xs mt-1">{label}</div></Card>
  );
  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {stat("Documents", usage.documents ?? "—")}
        {stat("Total characters", (usage.total_chars ?? 0).toLocaleString())}
        {stat("Tokens in", (usage.tokens_in ?? 0).toLocaleString())}
        {stat("Tokens out", (usage.tokens_out ?? 0).toLocaleString())}
      </div>
      <h3 className="text-sm font-semibold mb-2">Quality (corpus faithfulness)</h3>
      {evalm ? (
        <div className="flex flex-wrap gap-2">
          {Object.entries(evalm).map(([k, v]) => (
            <Pill key={k}>{k}: {typeof v === "number" ? (v as number).toFixed(3) : String(v)}</Pill>
          ))}
        </div>
      ) : <div className="muted text-sm">no eval data yet</div>}
    </div>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [email, setEmail] = useState(""); const [pass, setPass] = useState(""); const [role, setRole] = useState("viewer");
  const load = () => api.get("/users").then((r) => setUsers(r.users)).catch((e) => toast(e.message, "err"));
  useEffect(() => { load(); }, []);

  async function add() {
    if (!email.trim() || pass.length < 8) { toast("Email + password (≥8 chars) required", "err"); return; }
    try { await api.post("/users", { email: email.trim(), password: pass, role }); setEmail(""); setPass(""); setRole("viewer"); load(); toast("User created"); }
    catch (e: any) { toast(e.message, "err"); }
  }
  const act = (fn: Promise<any>) => fn.then(load).then(() => toast("Updated")).catch((e: any) => toast(e.message, "err"));

  return (
    <div>
      <Card className="mb-4">
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
            <th className="py-2">Email</th><th>Role</th><th>Status</th><th>Last login</th><th></th>
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
                <td className="muted">{u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : "—"}</td>
                <td className="text-right">
                  <button className="text-acc mr-3" onClick={() => act(api.patch(`/users/${u.id}`, { disabled: !u.disabled }))}>{u.disabled ? "enable" : "disable"}</button>
                  <button className="text-red-400" onClick={() => { if (confirm(`Delete ${u.email}?`)) act(api.del(`/users/${u.id}`)); }}><Trash2 className="w-4 h-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function KeysTab() {
  const [keys, setKeys] = useState<any[] | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const load = () => api.get("/api-keys").then((r) => setKeys(r.keys)).catch((e) => toast(e.message, "err"));
  useEffect(() => { load(); }, []);
  async function create(scopes: string[]) {
    try { const r = await api.post("/api-keys", { scopes }); setFresh(r.api_key); load(); } catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <div>
      <Card className="mb-4">
        <div className="text-sm mb-2">Create a service key (shown once):</div>
        <div className="flex gap-2 flex-wrap">
          <Button onClick={() => create(["read"])}>read</Button>
          <Button onClick={() => create(["read", "write"])}>read + write</Button>
          <Button onClick={() => create(["read", "write", "admin"])}>admin</Button>
        </div>
        {fresh && (
          <div className="mt-3 flex items-center gap-2 bg-[#0b0e12] border border-acc/60 rounded p-2">
            <code className="text-acc text-sm break-all flex-1">{fresh}</code>
            <button className="text-mut hover:text-fg" onClick={() => { navigator.clipboard.writeText(fresh); toast("Copied"); }}><Copy className="w-4 h-4" /></button>
          </div>
        )}
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

const EVENTS = ["document.ready"];

function HooksTab() {
  const [hooks, setHooks] = useState<any[] | null>(null);
  const [url, setUrl] = useState(""); const [secret, setSecret] = useState("");
  const [events, setEvents] = useState<string[]>(["document.ready"]);
  const load = () => api.get("/webhooks").then((r) => setHooks(r.webhooks)).catch((e) => toast(e.message, "err"));
  useEffect(() => { load(); }, []);
  async function create() {
    if (!/^https?:\/\//.test(url)) { toast("Enter a valid http(s) URL", "err"); return; }
    if (!events.length) { toast("Select at least one event", "err"); return; }
    try { await api.post("/webhooks", { url, events, secret }); setUrl(""); setSecret(""); load(); toast("Webhook added"); }
    catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <div>
      <Card className="mb-4">
        <div className="flex gap-2 flex-wrap items-center mb-2">
          <Input placeholder="https://example.com/hook" value={url} onChange={(e) => setUrl(e.target.value)} className="flex-1 min-w-[220px]" />
          <Input placeholder="signing secret (optional)" value={secret} onChange={(e) => setSecret(e.target.value)} className="w-52" />
          <Button primary onClick={create}>Add webhook</Button>
        </div>
        <div className="flex gap-3 text-sm">
          {EVENTS.map((ev) => (
            <label key={ev} className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={events.includes(ev)}
                onChange={(e) => setEvents((s) => e.target.checked ? [...s, ev] : s.filter((x) => x !== ev))} /> {ev}
            </label>
          ))}
        </div>
        <div className="muted text-xs mt-2">Deliveries are HMAC-signed (X-Tome-Signature) and SSRF-guarded.</div>
      </Card>
      {hooks === null ? <Spinner /> : hooks.length === 0 ? <EmptyState title="No webhooks" /> : (
        <table className="w-full text-sm">
          <thead className="text-mut text-left border-b border-line"><tr><th className="py-2">URL</th><th>Events</th><th></th></tr></thead>
          <tbody>
            {hooks.map((h) => (
              <tr key={h.id} className="border-b border-line/50">
                <td className="py-2 break-all">{h.url}</td>
                <td>{(h.events || []).map((e: string) => <Pill key={e}>{e}</Pill>)}</td>
                <td className="text-right"><button className="text-red-400" onClick={async () => { if (confirm("Delete webhook?")) { await api.del(`/webhooks/${h.id}`); load(); toast("Deleted"); } }}><Trash2 className="w-4 h-4 inline" /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
