// Knowledge graph: browse entities (concepts / codes / acronyms) extracted from the
// base, pivot to the sections that mention them and to related entities.
import { useEffect, useState } from "react";
import { Network, FileText, RefreshCw, Search } from "lucide-react";
import { graph, GraphEntity, EntityDetail } from "../lib/api";
import { Button, Input, Card, Pill, EmptyState, Spinner, toast } from "./ui";

export function GraphPanel({ onOpenDoc, canWrite }: { onOpenDoc: (id: number) => void; canWrite: boolean }) {
  const [q, setQ] = useState("");
  const [ents, setEnts] = useState<GraphEntity[] | null>(null);
  const [sel, setSel] = useState<EntityDetail | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try { setEnts((await graph.entities(q.trim())).entities); }
    catch (e: any) { toast(e?.message || "load failed", "err"); } finally { setBusy(false); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  async function open(id: number) { try { setSel(await graph.entity(id)); } catch (e: any) { toast(e.message, "err"); } }
  async function rebuild() {
    setBusy(true);
    try { const r = await graph.rebuild(); toast(`Graph rebuilt — ${r.entities} entities`); load(); }
    catch (e: any) { toast(e?.message || "rebuild failed", "err"); } finally { setBusy(false); }
  }

  return (
    <div className="flex-1 flex min-h-0">
      <div className="w-80 border-r border-line overflow-auto p-4 shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <Network className="w-5 h-5 text-acc" /><h2 className="text-lg font-semibold">Graph</h2>
          {canWrite && <button className="ml-auto text-mut hover:text-acc" title="Rebuild graph" onClick={rebuild}><RefreshCw className="w-4 h-4" /></button>}
        </div>
        <div className="flex gap-2 mb-3">
          <Input placeholder="filter entities…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} />
          <Button onClick={load}><Search className="w-4 h-4" /></Button>
        </div>
        {busy && !ents ? <Spinner /> : !ents || ents.length === 0
          ? <EmptyState title="No entities" hint={canWrite ? "Ingest documents, or rebuild the graph." : "Nothing here yet."} />
          : <div className="space-y-1">
              {ents.map((e) => (
                <button key={e.id} onClick={() => open(e.id)}
                  className={`w-full text-left px-2 py-1.5 rounded flex items-center gap-2 ${sel?.entity.id === e.id ? "bg-acc/15 text-acc" : "hover:bg-[#1e252e]"}`}>
                  <span className="truncate flex-1">{e.name}</span>
                  <Pill>{e.kind}</Pill>
                  <span className="muted text-xs">{e.mention_count}</span>
                </button>
              ))}
            </div>}
      </div>
      <div className="flex-1 overflow-auto p-6">
        {!sel ? <EmptyState icon={<Network className="w-10 h-10" />} title="Select an entity"
          hint="See where a concept is mentioned and which entities relate to it." />
          : (
            <div>
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-xl font-semibold">{sel.entity.name}</h3>
                <Pill>{sel.entity.kind}</Pill>
                <span className="muted text-sm">{sel.entity.mention_count} mentions</span>
              </div>
              {sel.neighbors.length > 0 && (
                <div className="mb-5">
                  <div className="muted uppercase text-xs tracking-wide mb-2">Related entities</div>
                  <div className="flex flex-wrap gap-2">
                    {sel.neighbors.map((n) => (
                      <button key={n.id} className="pill hover:border-acc hover:text-acc" onClick={() => open(n.id)}>
                        {n.name} <span className="muted">· {n.weight}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="muted uppercase text-xs tracking-wide mb-2">Mentioned in</div>
              {sel.sections.length === 0 ? <div className="muted text-sm">no sections</div>
                : <div className="space-y-2">
                    {sel.sections.map((s) => (
                      <Card key={s.section_id} onClick={() => onOpenDoc(s.document_id)}>
                        <div className="flex items-center gap-2"><FileText className="w-4 h-4 text-acc" />
                          <span className="font-medium">{s.heading}</span></div>
                        <div className="muted text-sm">{s.doc_title}</div>
                      </Card>
                    ))}
                  </div>}
            </div>
          )}
      </div>
    </div>
  );
}
