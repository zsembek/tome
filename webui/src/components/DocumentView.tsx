import { useEffect, useState } from "react";
import {
  Pencil, Trash2, History, Download, AlertTriangle, FileText, BookOpen, Check, X,
} from "lucide-react";
import { api, docs as dapi, Doc, Section } from "../lib/api";
import { Button, Pill, Modal, Card, Spinner, toast } from "./ui";
import { Markdown } from "./Markdown";

type Active = { kind: "full" } | { kind: "section"; id: number };

export function DocumentView({ docId, onChanged, canWrite = true }: { docId: number; onChanged: () => void; canWrite?: boolean }) {
  const [doc, setDoc] = useState<(Doc & { extract_confidence?: number | null }) | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [active, setActive] = useState<Active>({ kind: "full" });
  const [body, setBody] = useState<{ md: string; rev?: number; heading?: string } | null>(null);
  const [loadingBody, setLoadingBody] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [versions, setVersions] = useState<any[] | null>(null);
  const [conflict, setConflict] = useState<any | null>(null);

  async function loadMeta() {
    const [d, s] = await Promise.all([dapi.get(docId), dapi.sections(docId, 6)]);
    setDoc(d); setSections(s.sections);
  }
  async function loadBody(a: Active) {
    setLoadingBody(true); setEditing(false);
    try {
      if (a.kind === "full") {
        setBody({ md: (await dapi.content(docId)).markdown });
      } else {
        const r = await api.get(`/sections/${a.id}?subsections=true`);
        setBody({ md: r.markdown, rev: r.rev, heading: r.heading });
      }
    } catch (e: any) { toast(e?.message || "load failed", "err"); } finally { setLoadingBody(false); }
  }
  useEffect(() => { setActive({ kind: "full" }); loadMeta(); }, [docId]);
  useEffect(() => { loadBody(active); /* eslint-disable-next-line */ }, [active, docId]);

  async function startEdit() {
    if (active.kind !== "section") return;
    const r = await api.get(`/sections/${active.id}?subsections=false`);
    setEditText(r.markdown); setBody((b) => (b ? { ...b, rev: r.rev } : b)); setEditing(true);
  }
  async function saveEdit() {
    if (active.kind !== "section") return;
    try {
      await api.patch(`/sections/${active.id}`, { content: editText, rev: body?.rev });
      setEditing(false); await loadMeta(); await loadBody(active); toast("Section saved");
    } catch (e: any) {
      toast(e.status === 409 ? "Conflict — reload and retry" : e?.message || "save failed", "err");
    }
  }
  async function delSection(id: number) {
    if (!confirm("Delete this section and its subsections?")) return;
    await api.del(`/sections/${id}`); setActive({ kind: "full" }); await loadMeta(); toast("Section deleted");
  }
  async function delDoc() { if (confirm("Delete this document?")) { await dapi.remove(docId); onChanged(); toast("Document deleted"); } }
  async function rename() {
    const t = prompt("New title:", doc?.title); if (!t) return;
    await dapi.rename(docId, t); await loadMeta(); onChanged(); toast("Renamed");
  }

  if (!doc) return <div className="flex-1 flex items-center justify-center muted gap-2"><Spinner /> loading…</div>;
  const conf = doc.extract_confidence;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* sticky header */}
      <div className="border-b border-line px-5 py-3">
        {doc.status === "conflict" && (
          <Card className="mb-3 border-yellow-600/60">
            <AlertTriangle className="inline w-4 h-4 text-yellow-500 mr-1" />
            Re-import conflict — manual edits exist.{" "}
            <button className="text-acc underline" onClick={async () => setConflict(await api.get(`/documents/${docId}/conflict/sections`))}>Compare & resolve</button>
          </Card>
        )}
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-xl font-semibold">{doc.title}</h2>
          {canWrite && <button className="text-mut hover:text-acc" onClick={rename} title="Rename"><Pencil className="w-4 h-4" /></button>}
          <div className="flex-1" />
          <button className="text-mut hover:text-acc" title="Versions" onClick={async () => setVersions((await api.get(`/documents/${docId}/versions`)).versions)}><History className="w-4 h-4" /></button>
          <button className="text-mut hover:text-acc" title="Export .zip" onClick={() => api.download(`/documents/${docId}/export`, `${doc.title}.zip`)}><Download className="w-4 h-4" /></button>
          {canWrite && <button className="text-mut hover:text-red-400" title="Delete" onClick={delDoc}><Trash2 className="w-4 h-4" /></button>}
        </div>
        {doc.summary && <p className="muted text-sm mt-1">{doc.summary}</p>}
        <div className="flex gap-2 mt-2 flex-wrap">
          <Pill>{doc.section_count} sections</Pill>
          <Pill>faithfulness {fmt(doc.faithfulness_score)}</Pill>
          {conf != null && <Pill>OCR confidence {fmt(conf)}</Pill>}
          {(doc.tags || []).map((t) => <Pill key={t}>{t}</Pill>)}
        </div>
      </div>

      {/* TOC + content */}
      <div className="flex-1 flex min-h-0">
        <nav className="w-64 border-r border-line overflow-auto p-2 shrink-0 text-sm">
          <button className={`w-full text-left px-2 py-1 rounded flex items-center gap-1.5 ${active.kind === "full" ? "bg-acc/15 text-acc" : "hover:bg-[#1e252e]"}`}
            onClick={() => setActive({ kind: "full" })}>
            <BookOpen className="w-3.5 h-3.5" /> Full document
          </button>
          <div className="muted uppercase text-[10px] tracking-wide mt-3 mb-1 px-2">Sections</div>
          {sections.length === 0 && <div className="muted px-2">no sections</div>}
          {sections.map((s) => (
            <button key={s.id}
              className={`w-full text-left px-2 py-1 rounded truncate ${active.kind === "section" && active.id === s.id ? "bg-acc/15 text-acc" : "hover:bg-[#1e252e] text-mut hover:text-fg"}`}
              style={{ paddingLeft: 8 + (s.level - 1) * 12 }}
              title={s.breadcrumb}
              onClick={() => setActive({ kind: "section", id: s.id })}>
              {s.heading}
            </button>
          ))}
        </nav>

        <div className="flex-1 overflow-auto p-6">
          {loadingBody ? <div className="muted flex items-center gap-2"><Spinner /> loading…</div>
            : editing && active.kind === "section" ? (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-medium">{body?.heading}</span>
                  <span className="muted text-xs">rev {body?.rev}</span>
                  <div className="flex-1" />
                  <Button primary onClick={saveEdit}><Check className="w-4 h-4" /> Save</Button>
                  <Button onClick={() => setEditing(false)}><X className="w-4 h-4" /> Cancel</Button>
                </div>
                <textarea className="input w-full h-[60vh] font-mono text-sm" value={editText} onChange={(e) => setEditText(e.target.value)} />
              </div>
            ) : (
              <div>
                {active.kind === "section" && canWrite && (
                  <div className="flex gap-2 mb-3">
                    <Button onClick={startEdit}><Pencil className="w-3.5 h-3.5" /> Edit section</Button>
                    <Button onClick={() => delSection(active.id)}><Trash2 className="w-3.5 h-3.5" /> Delete</Button>
                  </div>
                )}
                <article className="max-w-3xl"><Markdown>{body?.md || "_(empty)_"}</Markdown></article>
              </div>
            )}
        </div>
      </div>

      <Modal open={versions !== null} onClose={() => setVersions(null)} title="Version history">
        {(versions || []).length === 0 && <p className="muted">no versions</p>}
        {(versions || []).map((v) => (
          <div key={v.version_no} className="card mb-2 text-sm flex items-center gap-2">
            <Pill>v{v.version_no}</Pill> <span>{v.state} · {v.change_kind} · {v.author}</span>
            <span className="muted ml-auto">faith {fmt(v.faithfulness_score)}</span>
          </div>
        ))}
      </Modal>

      <ConflictModal docId={docId} data={conflict} onClose={() => setConflict(null)}
        onResolved={() => { setConflict(null); loadMeta(); onChanged(); }} />
    </div>
  );
}

function fmt(n: number | null | undefined) { return n == null ? "—" : Number(n).toFixed(2); }

function ConflictModal({ docId, data, onClose, onResolved }: { docId: number; data: any; onClose: () => void; onResolved: () => void }) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  if (!data) return null;
  const changed = (data.sections || []).filter((r: any) => r.status !== "unchanged");
  async function resolve() {
    await api.post(`/documents/${docId}/conflict/resolve_sections`, { choices });
    toast("Conflict resolved"); onResolved();
  }
  return (
    <Modal open wide onClose={onClose} title="Resolve conflict per section">
      {changed.length === 0 && <p className="muted">no differences</p>}
      {changed.map((r: any) => (
        <Card key={r.heading} className="mb-3">
          <div className="font-medium mb-1">{r.heading} <Pill>{r.status}</Pill> {r.manually_edited && <Pill>manually edited</Pill>}</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><div className="muted mb-1">current</div><pre className="max-h-40 overflow-auto whitespace-pre-wrap">{r.current ?? "—"}</pre></div>
            <div><div className="muted mb-1">incoming</div><pre className="max-h-40 overflow-auto whitespace-pre-wrap">{r.incoming ?? "—"}</pre></div>
          </div>
          <div className="flex gap-2 mt-2">
            <Button primary={choices[r.heading] === "keep_manual"} onClick={() => setChoices({ ...choices, [r.heading]: "keep_manual" })}>keep current</Button>
            <Button primary={choices[r.heading] === "take_import"} onClick={() => setChoices({ ...choices, [r.heading]: "take_import" })}>take incoming</Button>
          </div>
        </Card>
      ))}
      {changed.length > 0 && <Button primary onClick={resolve}>Apply selection</Button>}
    </Modal>
  );
}
