import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { api, SearchHit } from "../lib/api";
import { Button, Input, Card, Pill, EmptyState, Spinner } from "./ui";
import { Markdown } from "./Markdown";

export function SearchPanel({ onOpenSection }: { onOpenSection: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    if (!q.trim()) return;
    setBusy(true);
    try { setHits((await api.get(`/search?q=${encodeURIComponent(q)}&mode=${mode}&top_k=20`)).results); }
    finally { setBusy(false); }
  }
  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex gap-2 mb-4">
        <Input placeholder="Search the knowledge base…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} className="flex-1" />
        <select className="input w-32" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="hybrid">hybrid</option><option value="bm25">keyword</option><option value="vector">semantic</option>
        </select>
        <Button primary onClick={run}><Search className="w-4 h-4" /> Search</Button>
      </div>
      {busy && <div className="muted flex items-center gap-2"><Spinner /> searching…</div>}
      {!busy && hits && hits.length === 0 && <EmptyState title="No matches" hint="Try different terms or switch the search mode." />}
      {(hits || []).map((h) => (
        <Card key={h.id} className="mb-2" onClick={() => onOpenSection(h.id)}>
          <div className="font-medium flex items-center gap-2">{h.heading} <Pill>{Number(h.score).toFixed(3)}</Pill></div>
          <div className="muted text-sm">{h.doc_title} · {h.breadcrumb}</div>
          <div className="text-sm mt-1 text-mut">{(h.content || "").slice(0, 240)}…</div>
        </Card>
      ))}
    </div>
  );
}

export function SectionView({ id, onBack }: { id: number; onBack: () => void }) {
  const [data, setData] = useState<any>(null);
  useEffect(() => { api.get(`/sections/${id}?subsections=true`).then(setData); }, [id]);
  if (!data) return <div className="flex-1 p-6 muted flex items-center gap-2"><Spinner /> loading…</div>;
  return (
    <div className="flex-1 overflow-auto p-6">
      <Button onClick={onBack}>← back to search</Button>
      <h2 className="text-xl font-semibold my-3">{data.heading}</h2>
      <article className="max-w-3xl"><Markdown>{data.markdown}</Markdown></article>
    </div>
  );
}
