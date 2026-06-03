// Knowledge graph: an interactive force-directed network of entities (nodes) connected
// by co-occurrence relations (edges). Click a node to see its documents + neighbors and
// recenter; drag to pan, wheel to zoom.
import { useEffect, useMemo, useRef, useState } from "react";
import { Network, FileText, RefreshCw, ZoomIn, ZoomOut } from "lucide-react";
import { graph, GraphData, EntityDetail } from "../lib/api";
import { Button, Pill, EmptyState, Spinner, toast } from "./ui";

const W = 1000, H = 680;
const KIND_COLOR: Record<string, string> = { concept: "#4f9eff", code: "#34d399", acronym: "#c084fc" };

type Pos = { id: number; x: number; y: number };

function layout(data: GraphData): Pos[] {
  const n = data.nodes.length;
  if (!n) return [];
  const pos: Pos[] = data.nodes.map((nd, i) => ({
    id: nd.id,
    x: W / 2 + Math.cos((2 * Math.PI * i) / n) * Math.min(W, H) * 0.34,
    y: H / 2 + Math.sin((2 * Math.PI * i) / n) * Math.min(W, H) * 0.34,
  }));
  const idx = new Map(pos.map((p, i) => [p.id, i]));
  const k = Math.sqrt((W * H) / n) * 0.55;
  const iters = 220;
  for (let it = 0; it < iters; it++) {
    const disp = pos.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      let dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
      let d = Math.hypot(dx, dy) || 0.01;
      const f = (k * k) / d;
      disp[i].x += (dx / d) * f; disp[i].y += (dy / d) * f;
      disp[j].x -= (dx / d) * f; disp[j].y -= (dy / d) * f;
    }
    for (const e of data.edges) {
      const a = idx.get(e.src), b = idx.get(e.dst);
      if (a == null || b == null) continue;
      let dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
      let d = Math.hypot(dx, dy) || 0.01;
      const f = ((d * d) / k) * (1 + Math.log(1 + e.weight)) * 0.08;
      disp[a].x -= (dx / d) * f; disp[a].y -= (dy / d) * f;
      disp[b].x += (dx / d) * f; disp[b].y += (dy / d) * f;
    }
    const t = (1 - it / iters) * Math.min(W, H) * 0.05 + 1;
    for (let i = 0; i < n; i++) {
      disp[i].x += (W / 2 - pos[i].x) * 0.012; disp[i].y += (H / 2 - pos[i].y) * 0.012;
      const dl = Math.hypot(disp[i].x, disp[i].y) || 0.01;
      pos[i].x += (disp[i].x / dl) * Math.min(dl, t);
      pos[i].y += (disp[i].y / dl) * Math.min(dl, t);
      pos[i].x = Math.max(24, Math.min(W - 24, pos[i].x));
      pos[i].y = Math.max(24, Math.min(H - 24, pos[i].y));
    }
  }
  return pos;
}

export function GraphPanel({ onOpenDoc, canWrite }: { onOpenDoc: (id: number) => void; canWrite: boolean }) {
  const [data, setData] = useState<GraphData | null>(null);
  const [sel, setSel] = useState<EntityDetail | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState({ z: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  async function load() {
    setBusy(true);
    try { setData(await graph.overview(80)); } catch (e: any) { toast(e?.message || "load failed", "err"); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);
  async function open(id: number) { try { setSel(await graph.entity(id)); } catch (e: any) { toast(e.message, "err"); } }
  async function rebuild() {
    setBusy(true);
    try { const r = await graph.rebuild(); toast(`Graph rebuilt — ${r.entities} entities`); await load(); }
    catch (e: any) { toast(e?.message || "rebuild failed", "err"); } finally { setBusy(false); }
  }

  const pos = useMemo(() => (data ? layout(data) : []), [data]);
  const posById = useMemo(() => new Map(pos.map((p) => [p.id, p])), [pos]);
  const nodeById = useMemo(() => new Map((data?.nodes || []).map((n) => [n.id, n])), [data]);
  const maxM = Math.max(1, ...(data?.nodes || []).map((n) => n.mention_count));
  const focus = sel?.entity.id ?? hover;
  const focusedEdges = useMemo(() => {
    const s = new Set<number>();
    if (focus != null) (data?.edges || []).forEach((e) => { if (e.src === focus || e.dst === focus) { s.add(e.src); s.add(e.dst); } });
    return s;
  }, [focus, data]);

  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    setView((v) => ({ ...v, z: Math.min(3, Math.max(0.4, v.z * (e.deltaY < 0 ? 1.1 : 0.9))) }));
  }

  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center gap-2 p-3 border-b border-line">
          <Network className="w-5 h-5 text-acc" /><h2 className="text-lg font-semibold">Knowledge Graph</h2>
          {data && <span className="muted text-sm">· {data.nodes.length} entities · {data.edges.length} links</span>}
          <div className="flex-1" />
          <Button onClick={() => setView((v) => ({ ...v, z: Math.min(3, v.z * 1.2) }))}><ZoomIn className="w-4 h-4" /></Button>
          <Button onClick={() => setView((v) => ({ ...v, z: Math.max(0.4, v.z / 1.2) }))}><ZoomOut className="w-4 h-4" /></Button>
          <Button onClick={() => setView({ z: 1, x: 0, y: 0 })}>reset</Button>
          {canWrite && <Button onClick={rebuild}><RefreshCw className="w-4 h-4" /> rebuild</Button>}
        </div>

        {busy && !data ? <div className="p-6 muted flex items-center gap-2"><Spinner /> loading…</div>
          : !data || data.nodes.length === 0
            ? <EmptyState icon={<Network className="w-10 h-10" />} title="The graph is empty"
                hint={canWrite ? "Ingest documents, then “rebuild” to extract entities & relations." : "No entities yet."} />
            : (
              <svg className="flex-1 w-full bg-[#0b0e12] cursor-grab" viewBox={`0 0 ${W} ${H}`}
                onWheel={onWheel}
                onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; }}
                onMouseUp={() => { drag.current = null; }}
                onMouseLeave={() => { drag.current = null; setHover(null); }}
                onMouseMove={(e) => {
                  if (!drag.current) return;
                  const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
                  drag.current = { x: e.clientX, y: e.clientY };
                  setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
                }}>
                <g transform={`translate(${view.x},${view.y}) scale(${view.z})`}>
                  {data.edges.map((e, i) => {
                    const a = posById.get(e.src), b = posById.get(e.dst);
                    if (!a || !b) return null;
                    const on = focus != null && (e.src === focus || e.dst === focus);
                    return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={on ? "#4f9eff" : "#273141"} strokeWidth={Math.min(4, 0.4 + Math.log(1 + e.weight))}
                      strokeOpacity={focus == null || on ? 0.9 : 0.15} />;
                  })}
                  {pos.map((p) => {
                    const nd = nodeById.get(p.id)!;
                    const r = 5 + (nd.mention_count / maxM) * 16;
                    const dim = focus != null && p.id !== focus && !focusedEdges.has(p.id);
                    return (
                      <g key={p.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer" }}
                        onMouseEnter={() => setHover(p.id)} onMouseLeave={() => setHover(null)}
                        onClick={() => open(p.id)} opacity={dim ? 0.25 : 1}>
                        <circle r={r} fill={KIND_COLOR[nd.kind] || "#4f9eff"}
                          stroke={p.id === sel?.entity.id ? "#fff" : "#0b0e12"} strokeWidth={p.id === sel?.entity.id ? 2 : 1} />
                        {(r > 9 || hover === p.id || focus === p.id) && (
                          <text x={r + 3} y={4} fontSize={12} fill="#c9d4e3" className="select-none">{nd.name}</text>
                        )}
                      </g>
                    );
                  })}
                </g>
              </svg>
            )}
        <div className="muted text-xs px-3 py-1.5 border-t border-line flex gap-3">
          <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: KIND_COLOR.concept }} />concept</span>
          <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: KIND_COLOR.code }} />code</span>
          <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: KIND_COLOR.acronym }} />acronym</span>
          <span className="ml-auto">node size = mentions · edge width = co-occurrence</span>
        </div>
      </div>

      {/* detail side panel */}
      <div className="w-80 border-l border-line overflow-auto p-4 shrink-0">
        {!sel ? <EmptyState title="Click a node" hint="See where an entity is mentioned and what it relates to." />
          : (
            <div>
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <h3 className="text-lg font-semibold">{sel.entity.name}</h3>
                <Pill>{sel.entity.kind}</Pill><span className="muted text-sm">{sel.entity.mention_count} mentions</span>
              </div>
              {sel.neighbors.length > 0 && (
                <div className="mb-4">
                  <div className="muted uppercase text-xs tracking-wide mb-2">Related</div>
                  <div className="flex flex-wrap gap-1.5">
                    {sel.neighbors.map((nb) => (
                      <button key={nb.id} className="pill hover:border-acc hover:text-acc" onClick={() => open(nb.id)}>
                        {nb.name} <span className="muted">· {nb.weight}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="muted uppercase text-xs tracking-wide mb-2">Mentioned in</div>
              {sel.sections.length === 0 ? <div className="muted text-sm">no sections</div>
                : sel.sections.map((s) => (
                  <button key={s.section_id} className="block w-full text-left py-1 hover:text-acc"
                    onClick={() => onOpenDoc(s.document_id)}>
                    <FileText className="w-3.5 h-3.5 inline mr-1" />{s.heading}
                    <span className="muted text-xs block ml-5">{s.doc_title}</span>
                  </button>
                ))}
            </div>
          )}
      </div>
    </div>
  );
}
