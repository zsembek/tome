import { useEffect, useState } from "react";
import { Pencil, Trash2, History, Download, AlertTriangle, FileText } from "lucide-react";
import { api, Doc, Section } from "../lib/api";
import { Button, Pill, Modal, Card } from "./ui";
import { Markdown } from "./Markdown";

export function DocumentView({ docId, onChanged, canWrite = true }: { docId: number; onChanged: () => void; canWrite?: boolean }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [editRev, setEditRev] = useState(0);
  const [versions, setVersions] = useState<any[] | null>(null);
  const [conflict, setConflict] = useState<any | null>(null);
  const [full, setFull] = useState<string | null>(null);

  async function load() {
    const d = await api.get(`/documents/${docId}`);
    setDoc(d);
    setSections((await api.get(`/documents/${docId}/sections?depth=4`)).sections);
  }
  useEffect(() => { load(); setFull(null); setVersions(null); }, [docId]);

  async function startEdit(s: Section) {
    const r = await api.get(`/sections/${s.id}?subsections=false`);
    setEditing(s.id); setEditText(r.markdown); setEditRev(r.rev);
  }
  async function saveEdit() {
    try {
      await api.patch(`/sections/${editing}`, { content: editText, rev: editRev });
      setEditing(null); load();
    } catch (e: any) {
      alert(e.status === 409 ? "Conflict: the section was changed. Please reload." : e.message);
    }
  }
  async function delSection(id: number) { if (confirm("Delete section?")) { await api.del(`/sections/${id}`); load(); } }
  async function delDoc() { if (confirm("Delete document?")) { await api.del(`/documents/${docId}`); onChanged(); } }
  async function rename() {
    const t = prompt("New title:", doc?.title); if (!t) return;
    await api.patch(`/documents/${docId}`, { title: t }); load(); onChanged();
  }
  async function openConflict() {
    setConflict(await api.get(`/documents/${docId}/conflict/sections`));
  }

  if (!doc) return <div className="muted p-6">loading…</div>;

  return (
    <div className="flex-1 overflow-auto p-6">
      {doc.status === "conflict" && (
        <Card className="mb-3 border-yellow-600/60">
          <AlertTriangle className="inline w-4 h-4 text-yellow-500 mr-1" />
          Re-import conflict — manual edits exist.{" "}
          <Button onClick={openConflict}>Compare & resolve per section</Button>
        </Card>
      )}
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <h2 className="text-xl font-semibold">{doc.title}</h2>
        {canWrite && <button className="text-acc text-sm" onClick={rename}><Pencil className="inline w-3.5 h-3.5" /></button>}
        {canWrite && <button className="text-red-400 text-sm" onClick={delDoc}><Trash2 className="inline w-3.5 h-3.5" /></button>}
        <button className="text-acc text-sm" onClick={async () => setVersions((await api.get(`/documents/${docId}/versions`)).versions)}><History className="inline w-3.5 h-3.5" /> versions</button>
        <button className="text-acc text-sm" onClick={() => api.download(`/documents/${docId}/export`, `${doc.title}.zip`)}><Download className="inline w-3.5 h-3.5" /> export</button>
      </div>
      <p className="muted mb-2">{doc.summary}</p>
      <div className="flex gap-2 mb-3">
        <Pill>sections: {doc.section_count}</Pill>
        <Pill>faithfulness: {doc.faithfulness_score ?? "—"}</Pill>
        <Button onClick={async () => setFull((await api.get(`/documents/${docId}/content`)).markdown)}>
          <FileText className="w-4 h-4" /> read full
        </Button>
      </div>

      {full !== null && <div className="mb-4 card"><Markdown>{full}</Markdown></div>}

      {sections.map((s) => (
        <div key={s.id} className="border-l-2 border-line pl-3 my-2">
          <div className="flex items-center gap-2">
            <span className="font-medium">{"#".repeat(s.level)} {s.heading}</span>
            {canWrite && <button className="text-acc text-xs" onClick={() => startEdit(s)}>✎</button>}
            {canWrite && <button className="text-red-400 text-xs" onClick={() => delSection(s.id)}>🗑</button>}
          </div>
          {editing === s.id ? (
            <div className="mt-1">
              <textarea className="input h-40 font-mono" value={editText} onChange={(e) => setEditText(e.target.value)} />
              <div className="flex gap-2 mt-1">
                <Button primary onClick={saveEdit}>Save</Button>
                <Button onClick={() => setEditing(null)}>Cancel</Button>
                <span className="muted text-xs self-center">rev {editRev}</span>
              </div>
            </div>
          ) : (
            <div className="muted text-xs">{s.breadcrumb} · {s.char_count} chars</div>
          )}
        </div>
      ))}

      <Modal open={versions !== null} onClose={() => setVersions(null)} title="Version history">
        {(versions || []).map((v) => (
          <div key={v.version_no} className="card mb-2 text-sm">
            v{v.version_no} · {v.state} · {v.change_kind} · {v.author} · faith {v.faithfulness_score ?? "—"}
          </div>
        ))}
      </Modal>

      <ConflictModal docId={docId} data={conflict} onClose={() => setConflict(null)} onResolved={() => { setConflict(null); load(); onChanged(); }} />
    </div>
  );
}

function ConflictModal({ docId, data, onClose, onResolved }: { docId: number; data: any; onClose: () => void; onResolved: () => void }) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  if (!data) return null;
  const changed = (data.sections || []).filter((r: any) => r.status !== "unchanged");
  async function resolve() {
    await api.post(`/documents/${docId}/conflict/resolve_sections`, { choices });
    onResolved();
  }
  return (
    <Modal open wide onClose={onClose} title="Resolve conflict per section">
      {changed.length === 0 && <p className="muted">no differences</p>}
      {changed.map((r: any) => (
        <Card key={r.heading} className="mb-3">
          <div className="font-medium mb-1">{r.heading} <Pill>{r.status}</Pill> {r.manually_edited && <Pill>manually edited</Pill>}</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><div className="muted mb-1">current</div><pre className="max-h-40">{r.current ?? "—"}</pre></div>
            <div><div className="muted mb-1">incoming</div><pre className="max-h-40">{r.incoming ?? "—"}</pre></div>
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
