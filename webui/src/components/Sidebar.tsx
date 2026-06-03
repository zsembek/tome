import { useEffect, useRef, useState } from "react";
import {
  Folder as FolderIcon, FileText, Upload, FolderPlus, ChevronRight, ChevronDown,
  MoreVertical, Plus,
} from "lucide-react";
import { folders as fapi, docs as dapi, Folder, Doc } from "../lib/api";
import { Button, Input, Menu, MenuItem, Spinner, toast } from "./ui";

/**
 * Folder tree with real nesting, per-node actions (new subfolder / rename / delete /
 * upload here), drag-a-document-to-move, and drag-a-file-to-upload-here. The selected
 * folder is the default upload target.
 */
export function Sidebar({ onOpenDoc, refreshKey, onUpload, canWrite = true, selectedId, onSelect, openDocId }: {
  onOpenDoc: (id: number) => void;
  refreshKey: number;
  onUpload: (file: File, folderId?: number | null) => void | Promise<void>;
  canWrite?: boolean;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  openDocId?: number | null;
}) {
  const [roots, setRoots] = useState<Folder[] | null>(null);
  const [children, setChildren] = useState<Record<number, Folder[]>>({});
  const [docs, setDocs] = useState<Record<number, Doc[]>>({});
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [creatingUnder, setCreatingUnder] = useState<number | "root" | null>(null);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const [dropTarget, setDropTarget] = useState<number | "root" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function loadRoots() {
    try { setRoots((await fapi.roots()).folders); } catch (e: any) { toast(e?.message || "load failed", "err"); }
  }
  async function loadNode(id: number) {
    try {
      const [c, d] = await Promise.all([fapi.children(id), fapi.documents(id)]);
      setChildren((s) => ({ ...s, [id]: c.folders }));
      setDocs((s) => ({ ...s, [id]: d.documents }));
    } catch (e: any) { toast(e?.message || "load failed", "err"); }
  }
  function refreshNode(parentId: number | null) { parentId == null ? loadRoots() : loadNode(parentId); }

  useEffect(() => { loadRoots(); setChildren({}); setDocs({}); }, [refreshKey]);

  async function expand(f: Folder, force?: boolean) {
    const next = force ?? !open[f.id];
    setOpen((o) => ({ ...o, [f.id]: next }));
    if (next && !children[f.id]) await loadNode(f.id);
  }

  async function createFolder(parent: number | null) {
    const name = newName.trim();
    if (!name) return;
    try {
      await fapi.create(name, parent);
      setNewName(""); setCreatingUnder(null);
      if (parent == null) loadRoots();
      else { await loadNode(parent); setOpen((o) => ({ ...o, [parent]: true })); }
      toast(`Folder “${name}” created`);
    } catch (e: any) { toast(e?.message || "create failed", "err"); }
  }
  async function doRename(f: Folder) {
    const name = renameVal.trim();
    if (!name || name === f.name) { setRenaming(null); return; }
    try { await fapi.rename(f.id, name); setRenaming(null); refreshNode(f.parent_id); toast("Renamed"); }
    catch (e: any) { toast(e?.message || "rename failed", "err"); }
  }
  async function removeFolder(f: Folder) {
    if (!confirm(`Delete folder “${f.name}” and everything inside it?`)) return;
    try { await fapi.remove(f.id); refreshNode(f.parent_id); toast("Folder deleted"); }
    catch (e: any) { toast(e?.message || "delete failed", "err"); }
  }
  async function moveDocTo(docId: number, folderId: number, fromFolder: number | null) {
    try {
      await dapi.move(docId, folderId);
      if (fromFolder != null) loadNode(fromFolder);
      loadNode(folderId); setOpen((o) => ({ ...o, [folderId]: true }));
      toast("Document moved");
    } catch (e: any) { toast(e?.message || "move failed", "err"); }
  }

  const Row = ({ f, depth }: { f: Folder; depth: number }) => {
    const isOpen = open[f.id];
    const hasKids = f.has_children || (f.doc_count ?? 0) > 0;
    const selected = selectedId === f.id;
    const dz = dropTarget === f.id;
    return (
      <div>
        <div
          className={`group px-1.5 py-1 rounded flex items-center gap-0.5 cursor-pointer
            ${selected ? "bg-acc/15 text-acc" : "hover:bg-[#1e252e]"} ${dz ? "ring-1 ring-acc" : ""}`}
          style={{ paddingLeft: depth * 14 + 4 }}
          onClick={() => { onSelect(f.id); expand(f); }}
          onDragOver={(e) => { e.preventDefault(); setDropTarget(f.id); }}
          onDragLeave={() => setDropTarget((t) => (t === f.id ? null : t))}
          onDrop={(e) => {
            e.preventDefault(); setDropTarget(null);
            const docId = e.dataTransfer.getData("tome/doc");
            if (docId) { moveDocTo(Number(docId), f.id, Number(e.dataTransfer.getData("tome/doc-folder")) || null); return; }
            if (e.dataTransfer.files[0]) onUpload(e.dataTransfer.files[0], f.id);
          }}
        >
          <button onClick={(e) => { e.stopPropagation(); expand(f); }} className="shrink-0">
            {hasKids ? (isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />)
              : <span className="w-3.5 inline-block" />}
          </button>
          <FolderIcon className={`w-4 h-4 mr-1 shrink-0 ${selected ? "text-acc" : "text-acc/80"}`} />
          {renaming === f.id ? (
            <input autoFocus className="input py-0 h-6 text-sm" value={renameVal}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setRenameVal(e.target.value)}
              onBlur={() => doRename(f)} onKeyDown={(e) => { if (e.key === "Enter") doRename(f); if (e.key === "Escape") setRenaming(null); }} />
          ) : (
            <span className="truncate flex-1">{f.name}</span>
          )}
          <span className="muted text-xs">{f.doc_count || ""}</span>
          {canWrite && renaming !== f.id && (
            <span className="opacity-0 group-hover:opacity-100">
              <Menu trigger={<MoreVertical className="w-3.5 h-3.5 text-mut hover:text-fg" />}>
                {(close) => (<>
                  <MenuItem onClick={() => { close(); setCreatingUnder(f.id); setNewName(""); setOpen((o) => ({ ...o, [f.id]: true })); }}>New subfolder</MenuItem>
                  <MenuItem onClick={() => { close(); setRenaming(f.id); setRenameVal(f.name); }}>Rename</MenuItem>
                  <MenuItem onClick={() => { close(); fileRef.current!.dataset.target = String(f.id); fileRef.current?.click(); }}>Upload here…</MenuItem>
                  <MenuItem danger onClick={() => { close(); removeFolder(f); }}>Delete</MenuItem>
                </>)}
              </Menu>
            </span>
          )}
        </div>

        {isOpen && (
          <div>
            {creatingUnder === f.id && (
              <div className="flex gap-1 my-1" style={{ paddingLeft: (depth + 1) * 14 + 8 }}>
                <Input autoFocus className="py-0 h-6 text-sm" placeholder="subfolder name" value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") createFolder(f.id); if (e.key === "Escape") setCreatingUnder(null); }} />
                <Button onClick={() => createFolder(f.id)}><Plus className="w-3.5 h-3.5" /></Button>
              </div>
            )}
            {(docs[f.id] || []).map((d) => (
              <div key={`d${d.id}`} draggable={canWrite}
                onDragStart={(e) => { e.dataTransfer.setData("tome/doc", String(d.id)); e.dataTransfer.setData("tome/doc-folder", String(f.id)); }}
                className={`px-1.5 py-1 rounded cursor-pointer truncate flex items-center gap-1
                  ${openDocId === d.id ? "bg-acc/15 text-acc" : "text-mut hover:bg-[#1e252e] hover:text-fg"}`}
                style={{ paddingLeft: (depth + 1) * 14 + 20 }}
                onClick={(e) => { e.stopPropagation(); onOpenDoc(d.id); }}>
                <FileText className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{d.title}</span>
                {d.status && d.status !== "ready" && <span className="muted text-[10px]">· {d.status}</span>}
              </div>
            ))}
            {(children[f.id] || []).map((c) => <Row key={`f${c.id}`} f={{ ...c, parent_id: f.id }} depth={depth + 1} />)}
          </div>
        )}
      </div>
    );
  };

  return (
    <aside className="w-[320px] border-r border-line overflow-auto p-3 shrink-0 flex flex-col">
      {canWrite && (
        <div
          className={`rounded-lg border-2 border-dashed p-3 text-center text-sm mb-3 transition-colors
            ${dropTarget === "root" ? "border-acc text-fg bg-acc/5" : "border-line text-mut"}`}
          onDragOver={(e) => { e.preventDefault(); setDropTarget("root"); }}
          onDragLeave={() => setDropTarget((t) => (t === "root" ? null : t))}
          onDrop={(e) => { e.preventDefault(); setDropTarget(null); if (e.dataTransfer.files[0]) onUpload(e.dataTransfer.files[0], selectedId); }}>
          <Upload className="inline w-4 h-4 mr-1" />
          {selectedId ? "drop a file → selected folder" : "drop a file → auto-filed"}
          <div className="mt-1">
            <input ref={fileRef} type="file" className="hidden" onChange={(e) => {
              const f = e.target.files?.[0]; if (!f) return;
              const tgt = fileRef.current?.dataset.target;
              onUpload(f, tgt ? Number(tgt) : selectedId);
              if (fileRef.current) { fileRef.current.value = ""; delete fileRef.current.dataset.target; }
            }} />
            <Button onClick={() => { if (fileRef.current) delete fileRef.current.dataset.target; fileRef.current?.click(); }}>Browse…</Button>
          </div>
        </div>
      )}

      {canWrite && (
        <div className="flex items-center justify-between mb-1 px-1">
          <span className="muted text-xs uppercase tracking-wide">Folders</span>
          <button className="text-mut hover:text-acc" title="New top-level folder"
            onClick={() => { setCreatingUnder("root"); setNewName(""); onSelect(null); }}>
            <FolderPlus className="w-4 h-4" />
          </button>
        </div>
      )}
      {creatingUnder === "root" && (
        <div className="flex gap-1 mb-2">
          <Input autoFocus className="py-0 h-7 text-sm" placeholder="folder name" value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") createFolder(null); if (e.key === "Escape") setCreatingUnder(null); }} />
          <Button onClick={() => createFolder(null)}><Plus className="w-3.5 h-3.5" /></Button>
        </div>
      )}

      <div className="flex-1">
        {roots === null ? <div className="muted text-sm flex items-center gap-2"><Spinner /> loading…</div>
          : roots.length === 0 ? <div className="muted text-sm px-1">No folders yet. Create one or upload a file.</div>
            : roots.map((f) => <Row key={`f${f.id}`} f={{ ...f, parent_id: null }} depth={0} />)}
      </div>
    </aside>
  );
}
