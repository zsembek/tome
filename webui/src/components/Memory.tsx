// Agent memory: add memories, browse by tier, recall by query, view Markdown, forget.
import { useEffect, useState } from "react";
import { Trash2, Search, Plus } from "lucide-react";
import { memory, MemoryItem } from "../lib/api";
import { Button, Input, Card, Pill, EmptyState, Spinner, toast } from "./ui";
import { Markdown } from "./Markdown";

const TIERS = ["", "working", "episodic", "semantic", "procedural"];
const LABEL: Record<string, string> = {
  "": "All", working: "Working", episodic: "Episodic", semantic: "Semantic", procedural: "Procedural",
};

export function MemoryPanel({ canWrite }: { canWrite: boolean }) {
  const [tier, setTier] = useState("");
  const [q, setQ] = useState("");
  const [agent, setAgent] = useState("");
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // composer
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [newTier, setNewTier] = useState("semantic");
  const [newScope, setNewScope] = useState("shared");

  async function load() {
    setBusy(true); setErr("");
    try {
      const r = q.trim() ? await memory.recall(q.trim(), agent.trim()) : await memory.list(tier, agent.trim());
      setItems((r as any).results ?? (r as any).memories ?? []);
    } catch (e: any) { setErr(e?.message || "failed to load memory"); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tier]);

  async function save() {
    if (!text.trim()) { toast("Write something to remember", "err"); return; }
    try {
      await memory.remember(text.trim(), newTier, newScope, agent.trim());
      setText(""); setAdding(false); toast("Memory saved"); load();
    } catch (e: any) { toast(e?.message || "save failed", "err"); }
  }
  async function forget(id: number) {
    if (!confirm("Forget this memory? This is audited and cannot be undone.")) return;
    try { await memory.forget(id); toast("Forgotten"); load(); } catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center gap-2 mb-1">
        <h2 className="text-xl font-semibold">Memory</h2>
        <span className="muted text-sm">· agent-native, Markdown · tiers: working → episodic → semantic → procedural</span>
        <div className="flex-1" />
        {canWrite && <Button primary onClick={() => setAdding((v) => !v)}><Plus className="w-4 h-4" /> New memory</Button>}
      </div>
      <p className="muted text-sm mb-4">Long-term memory an agent reads &amp; writes (via MCP/REST). Add facts here, search with recall.</p>

      {adding && canWrite && (
        <Card className="mb-4">
          <textarea className="input w-full h-28 font-mono text-sm mb-2" placeholder="Markdown to remember — e.g. **The user prefers metric units.**"
            value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex gap-2 items-center flex-wrap">
            <select className="input w-36" value={newTier} onChange={(e) => setNewTier(e.target.value)}>
              {["semantic", "procedural", "episodic", "working"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select className="input w-36" value={newScope} onChange={(e) => setNewScope(e.target.value)}>
              <option value="shared">shared (workspace)</option><option value="agent">agent (private)</option>
            </select>
            <span className="muted text-xs">secrets are redacted on save</span>
            <div className="flex-1" />
            <Button onClick={() => setAdding(false)}>Cancel</Button>
            <Button primary onClick={save}>Save memory</Button>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {TIERS.map((t) => (
          <button key={t || "all"} className={`pill ${tier === t && !q ? "border-acc text-acc" : ""}`}
            onClick={() => { setQ(""); setTier(t); }}>{LABEL[t]}</button>
        ))}
        <div className="flex-1" />
        <Input placeholder="agent id (optional)" value={agent} onChange={(e) => setAgent(e.target.value)} className="w-40" />
        <Input placeholder="recall…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") load(); }} className="w-56" />
        <Button onClick={load}><Search className="w-4 h-4" /> Recall</Button>
      </div>

      {busy && items === null ? <div className="muted flex items-center gap-2"><Spinner /> loading…</div> : null}
      {err && <div className="text-red-400 text-sm mb-3">{err}</div>}
      {items !== null && items.length === 0 && !busy && (
        <EmptyState title="No memories" hint={canWrite ? "Add one above, or let an agent populate memory via MCP." : "Nothing remembered yet."} />
      )}

      <div className="flex flex-col gap-3">
        {(items || []).map((m) => (
          <Card key={m.id}>
            <div className="flex items-center gap-2 mb-2">
              <Pill>{m.tier}</Pill><Pill>{m.scope}</Pill>
              {m.title && <span className="font-medium">{m.title}</span>}
              <span className="muted text-xs">{m.agent_id}</span>
              <div className="flex-1" />
              {typeof m.score === "number" && <span className="muted text-xs">score {m.score}</span>}
              <span className="muted text-xs">★ {m.importance?.toFixed?.(2)}</span>
              {canWrite && <button className="text-mut hover:text-red-400" title="Forget" onClick={() => forget(m.id)}><Trash2 className="w-4 h-4" /></button>}
            </div>
            <Markdown>{m.content}</Markdown>
          </Card>
        ))}
      </div>
    </div>
  );
}
