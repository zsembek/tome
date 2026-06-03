// Agent memory browser: filter by tier, recall by query, view Markdown, forget.
import { useEffect, useState } from "react";
import { Trash2, Search } from "lucide-react";
import { memory, MemoryItem } from "../lib/api";
import { Button, Input, Card, Pill } from "./ui";
import { Markdown } from "./Markdown";

const TIERS = ["", "working", "episodic", "semantic", "procedural"];
const LABEL: Record<string, string> = {
  "": "All", working: "Working", episodic: "Episodic",
  semantic: "Semantic", procedural: "Procedural",
};

export function MemoryPanel({ canWrite }: { canWrite: boolean }) {
  const [tier, setTier] = useState("");
  const [q, setQ] = useState("");
  const [agent, setAgent] = useState("");
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    setBusy(true); setErr("");
    try {
      const r = q.trim()
        ? await memory.recall(q.trim(), agent.trim())
        : await memory.list(tier, agent.trim());
      setItems((r as any).results ?? (r as any).memories ?? []);
    } catch (e: any) {
      setErr(e?.message || "failed to load memory");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tier]);

  async function forget(id: number) {
    if (!confirm("Forget this memory? This is audited and cannot be undone.")) return;
    await memory.forget(id);
    load();
  }

  return (
    <div className="flex-1 p-6 overflow-auto">
      <div className="flex items-center gap-2 mb-4">
        <h2 className="text-lg font-semibold">Memory</h2>
        <span className="muted text-xs">agent-native, Markdown</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {TIERS.map((t) => (
          <button key={t || "all"}
            className={`pill ${tier === t && !q ? "border-acc text-acc" : ""}`}
            onClick={() => { setQ(""); setTier(t); }}>{LABEL[t]}</button>
        ))}
        <div className="flex-1" />
        <Input placeholder="agent id (optional)" value={agent}
               onChange={(e) => setAgent(e.target.value)} className="w-40" />
        <Input placeholder="recall…" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") load(); }} className="w-56" />
        <Button onClick={load}><Search className="w-4 h-4" /> Recall</Button>
      </div>

      {busy && <div className="muted">…</div>}
      {err && <div className="text-red-400 text-sm mb-3">{err}</div>}
      {!busy && items.length === 0 && <div className="muted">No memories yet.</div>}

      <div className="flex flex-col gap-3">
        {items.map((m) => (
          <Card key={m.id}>
            <div className="flex items-center gap-2 mb-2">
              <Pill>{m.tier}</Pill>
              <Pill>{m.scope}</Pill>
              {m.title && <span className="font-medium">{m.title}</span>}
              <span className="muted text-xs">{m.agent_id}</span>
              <div className="flex-1" />
              {typeof m.score === "number" && <span className="muted text-xs">score {m.score}</span>}
              <span className="muted text-xs">★ {m.importance?.toFixed?.(2)}</span>
              {canWrite && (
                <button className="text-mut hover:text-red-400" title="Forget"
                        onClick={() => forget(m.id)}><Trash2 className="w-4 h-4" /></button>
              )}
            </div>
            <Markdown>{m.content}</Markdown>
          </Card>
        ))}
      </div>
    </div>
  );
}
