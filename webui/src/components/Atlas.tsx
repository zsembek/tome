// Atlas: the knowledge base as a real, navigable hierarchy (folders → docs),
// not a flat list. Falls back to the generated Markdown overview on a second tab.
import { useEffect, useState } from "react";
import { Map, Folder, FileText, ChevronRight, ChevronDown, FileStack } from "lucide-react";
import { atlas, AtlasNode } from "../lib/api";
import { Tabs, EmptyState, Spinner } from "./ui";
import { Markdown } from "./Markdown";

export function AtlasPanel({ onOpenDoc }: { onOpenDoc: (id: number) => void }) {
  const [tab, setTab] = useState("map");
  const [tree, setTree] = useState<AtlasNode[] | null>(null);
  const [unfiled, setUnfiled] = useState<{ id: number; title: string }[]>([]);
  const [md, setMd] = useState<string | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    atlas.tree().then((r) => { setTree(r.tree); setUnfiled(r.unfiled || []); })
      .catch((e) => setErr(e?.message || "failed to load atlas"));
  }, []);
  useEffect(() => { if (tab === "md" && md === null) atlas.markdown().then((r) => setMd(r.markdown || "")); }, [tab]);

  const total = tree ? countDocs(tree) + unfiled.length : 0;

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center gap-2 mb-1">
        <Map className="w-5 h-5 text-acc" />
        <h2 className="text-xl font-semibold">Atlas</h2>
        {tree && <span className="muted text-sm">· {countFolders(tree)} folders · {total} documents</span>}
      </div>
      <p className="muted text-sm mb-4">A living map of the knowledge base — the structure an agent reads first.</p>

      <Tabs tabs={[{ id: "map", label: "Map" }, { id: "md", label: "Generated overview" }]} active={tab} onChange={setTab} />

      {err && <div className="text-red-400 text-sm">{err}</div>}

      {tab === "map" && (
        tree === null ? <div className="muted flex items-center gap-2"><Spinner /> loading…</div>
          : tree.length === 0 && unfiled.length === 0
            ? <EmptyState icon={<FileStack className="w-10 h-10" />} title="The base is empty"
                hint="Upload a document or create a folder to see the map fill in." />
            : <div className="text-sm">
                {tree.map((n) => <Node key={n.id} n={n} depth={0} onOpenDoc={onOpenDoc} />)}
                {unfiled.length > 0 && (
                  <div className="mt-4">
                    <div className="muted uppercase text-xs tracking-wide mb-1">Unfiled</div>
                    {unfiled.map((d) => (
                      <button key={d.id} className="flex items-center gap-1.5 text-mut hover:text-acc py-0.5"
                        onClick={() => onOpenDoc(d.id)}><FileText className="w-3.5 h-3.5" /> {d.title}</button>
                    ))}
                  </div>
                )}
              </div>
      )}

      {tab === "md" && (md === null ? <div className="muted flex items-center gap-2"><Spinner /> loading…</div>
        : <div className="card"><Markdown>{md || "_(empty)_"}</Markdown></div>)}
    </div>
  );
}

function Node({ n, depth, onOpenDoc }: { n: AtlasNode; depth: number; onOpenDoc: (id: number) => void }) {
  const [open, setOpen] = useState(depth < 1);
  const hasKids = n.children.length > 0 || n.documents.length > 0;
  return (
    <div>
      <div className="flex items-start gap-1.5 py-1 rounded hover:bg-[#1e252e] cursor-pointer"
        style={{ paddingLeft: depth * 18 }} onClick={() => setOpen((o) => !o)}>
        {hasKids ? (open ? <ChevronDown className="w-4 h-4 mt-0.5 shrink-0" /> : <ChevronRight className="w-4 h-4 mt-0.5 shrink-0" />)
          : <span className="w-4 inline-block shrink-0" />}
        <Folder className="w-4 h-4 mt-0.5 text-acc shrink-0" />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">{n.name}</span>
            <span className="muted text-xs">{n.doc_count} docs</span>
          </div>
          {n.description && <div className="muted text-xs truncate">{n.description}</div>}
        </div>
      </div>
      {open && (
        <div>
          {n.documents.map((d) => (
            <button key={d.id} className="flex items-center gap-1.5 text-mut hover:text-acc py-0.5"
              style={{ paddingLeft: (depth + 1) * 18 + 18 }} onClick={() => onOpenDoc(d.id)}>
              <FileText className="w-3.5 h-3.5 shrink-0" /> <span className="truncate">{d.title}</span>
            </button>
          ))}
          {n.children.map((c) => <Node key={c.id} n={c} depth={depth + 1} onOpenDoc={onOpenDoc} />)}
        </div>
      )}
    </div>
  );
}

function countDocs(nodes: AtlasNode[]): number {
  return nodes.reduce((s, n) => s + n.documents.length + countDocs(n.children), 0);
}
function countFolders(nodes: AtlasNode[]): number {
  return nodes.reduce((s, n) => s + 1 + countFolders(n.children), 0);
}
