import { useEffect, useRef, useState } from "react";
import { Folder as FolderIcon, FileText, Upload, FolderPlus, ChevronRight, ChevronDown } from "lucide-react";
import { api, Folder, Doc } from "../lib/api";
import { Button, Input } from "./ui";

// Lazy tree: a folder's children and documents load on expand (built for scale).
export function Sidebar({ onOpenDoc, refreshKey, onUpload, canWrite = true }: {
  onOpenDoc: (id: number) => void;
  refreshKey: number;
  onUpload: (file: File, folderPath?: string) => void | Promise<void>;
  canWrite?: boolean;
}) {
  const [roots, setRoots] = useState<Folder[]>([]);
  const [children, setChildren] = useState<Record<number, Folder[]>>({});
  const [docs, setDocs] = useState<Record<number, Doc[]>>({});
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [newFolder, setNewFolder] = useState("");
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function loadRoots() {
    try { setRoots((await api.get("/folders?lazy=true")).folders); } catch {}
  }
  useEffect(() => { loadRoots(); setChildren({}); setDocs({}); }, [refreshKey]);

  async function toggle(f: Folder) {
    const next = !open[f.id];
    setOpen((o) => ({ ...o, [f.id]: next }));
    if (next) {
      if (!children[f.id]) {
        const r = await api.get(`/folders?lazy=true&parent_id=${f.id}`);
        setChildren((c) => ({ ...c, [f.id]: r.folders }));
      }
      if (!docs[f.id]) {
        const r = await api.get(`/folders/${f.id}/documents?limit=200`);
        setDocs((d) => ({ ...d, [f.id]: r.documents }));
      }
    }
  }

  async function mkFolder() {
    if (!newFolder.trim()) return;
    await api.post("/folders", { path: newFolder.trim(), description: "" });
    setNewFolder(""); loadRoots();
  }
  function doUpload(file: File) {
    const path = prompt("Folder (A/B) or leave empty for auto-placement:", "") || undefined;
    onUpload(file, path);   // progress is shown from the start (in the Jobs panel)
  }

  const Node = ({ f, depth }: { f: Folder; depth: number }) => (
    <>
      <div className="px-1.5 py-0.5 rounded hover:bg-[#1e252e] cursor-pointer truncate flex items-center"
           style={{ paddingLeft: depth * 14 + 4 }} onClick={() => toggle(f)}>
        {f.has_children || (f.doc_count ?? 0) > 0
          ? (open[f.id] ? <ChevronDown className="w-3 h-3 mr-0.5" /> : <ChevronRight className="w-3 h-3 mr-0.5" />)
          : <span className="w-3 mr-0.5 inline-block" />}
        <FolderIcon className="w-3.5 h-3.5 mr-1 text-acc shrink-0" /> {f.name}
        <span className="muted text-xs ml-1">({f.doc_count})</span>
      </div>
      {open[f.id] && (
        <>
          {(docs[f.id] || []).map((d) => (
            <div key={`d${d.id}`} className="px-1.5 py-0.5 rounded hover:bg-[#1e252e] cursor-pointer truncate text-mut flex items-center"
                 style={{ paddingLeft: (depth + 1) * 14 + 16 }}
                 onClick={(e) => { e.stopPropagation(); onOpenDoc(d.id); }}>
              <FileText className="w-3.5 h-3.5 mr-1 shrink-0" /> {d.title}
            </div>
          ))}
          {(children[f.id] || []).map((c) => <Node key={`f${c.id}`} f={c} depth={depth + 1} />)}
        </>
      )}
    </>
  );

  return (
    <aside className="w-[300px] border-r border-line overflow-auto p-3 shrink-0">
      {canWrite && (
        <>
          <div className={`rounded-lg border-2 border-dashed p-3 text-center text-sm mb-3 ${over ? "border-acc text-fg" : "border-line text-mut"}`}
               onDragOver={(e) => { e.preventDefault(); setOver(true); }}
               onDragLeave={() => setOver(false)}
               onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) doUpload(e.dataTransfer.files[0]); }}>
            <Upload className="inline w-4 h-4 mr-1" /> drag a file here
            <div className="mt-1">
              <input ref={fileRef} type="file" className="hidden" onChange={(e) => e.target.files?.[0] && doUpload(e.target.files[0])} />
              <Button onClick={() => fileRef.current?.click()}>Browse</Button>
            </div>
          </div>
          <div className="flex gap-2 mb-3">
            <Input placeholder="new folder: A/B" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} />
            <Button onClick={mkFolder}><FolderPlus className="w-4 h-4" /></Button>
          </div>
        </>
      )}
      <div>{roots.map((f) => <Node key={`f${f.id}`} f={f} depth={0} />)}</div>
    </aside>
  );
}
