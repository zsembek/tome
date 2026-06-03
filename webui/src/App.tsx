import { useEffect, useState } from "react";
import { Search, Map, Shield, LogOut, Brain, Network } from "lucide-react";
import { api, auth, AuthStatus, Me } from "./lib/api";
import { Button, Toasts, toast } from "./components/ui";
import { Login } from "./components/Login";
import { Sidebar } from "./components/Sidebar";
import { DocumentView } from "./components/DocumentView";
import { SearchPanel, SectionView } from "./components/Panels";
import { AtlasPanel } from "./components/Atlas";
import { GraphPanel } from "./components/Graph";
import { AdminPanel } from "./components/Admin";
import { MemoryPanel } from "./components/Memory";
import { Jobs, JobInfo } from "./components/Jobs";

type View =
  | { t: "empty" } | { t: "doc"; id: number } | { t: "section"; id: number }
  | { t: "search" } | { t: "atlas" } | { t: "graph" } | { t: "memory" } | { t: "admin" };

export default function App() {
  const [view, setView] = useState<View>({ t: "empty" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [jobs, setJobs] = useState<Record<number, JobInfo>>({});
  const [booted, setBooted] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [selectedFolder, setSelectedFolder] = useState<number | null>(null);
  const refresh = () => setRefreshKey((k) => k + 1);

  async function checkAuth() {
    try {
      const st = await auth.status();
      setStatus(st);
      if (st.open_mode) {
        setMe({ email: null, role: "admin", scopes: ["read", "write", "admin"], via: "open" });
        setBooted(true); return;
      }
      try { setMe(await auth.me()); } catch { setMe(null); }
    } catch { setMe(null); }
    setBooted(true);
  }
  useEffect(() => { checkAuth(); }, []);

  function dismiss(id: number) { setJobs((j) => { const c = { ...j }; delete c[id]; return c; }); }

  function pollJob(jobId: number, name: string) {
    const t = setInterval(async () => {
      try {
        const j = await api.get(`/jobs/${jobId}`);
        setJobs((s) => ({ ...s, [jobId]: { name, stage: j.stage || j.status, status: j.status, progress: j.progress ?? 0, error: j.error } }));
        if (j.status === "done" || j.status === "error") {
          clearInterval(t); refresh();
          if (j.status === "error") toast(`“${name}” failed: ${j.error || "error"}`, "err");
          else if (j.stage === "conflict_pending") toast(`“${name}” needs conflict resolution`, "info");
          else toast(`“${name}” ingested`);
          setTimeout(() => dismiss(jobId), j.status === "error" ? 15000 : 4000);
        }
      } catch { clearInterval(t); }
    }, 1000);
  }

  async function startUpload(file: File, folderId?: number | null) {
    const tmp = -Date.now();
    setJobs((j) => ({ ...j, [tmp]: { name: file.name, stage: "upload", status: "uploading", progress: 0 } }));
    try {
      const r = await api.upload(file, { folderId: folderId ?? null });
      setJobs((j) => { const c = { ...j }; delete c[tmp]; c[r.job_id] = { name: file.name, stage: "queued", status: "queued", progress: 0 }; return c; });
      pollJob(r.job_id, file.name);
    } catch (e: any) {
      setJobs((j) => ({ ...j, [tmp]: { name: file.name, stage: "error", status: "error", progress: 0, error: e?.message || "upload failed" } }));
      toast(e?.message || "upload failed", "err");
      setTimeout(() => dismiss(tmp), 15000);
    }
  }

  async function doLogout() { await auth.logout(); setMe(null); setView({ t: "empty" }); }

  if (!booted) return <div className="h-full flex items-center justify-center muted">…</div>;
  if (!me && status) return <Login status={status} onAuthed={() => { setBooted(false); checkAuth(); }} />;

  const canWrite = !!me?.scopes.includes("write");
  const isAdmin = !!me?.scopes.includes("admin");
  const openDocId = view.t === "doc" ? view.id : null;
  const navBtn = (active: boolean) => active ? "text-acc" : "";

  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-line">
        <img src="/favicon.svg" alt="Tome" className="w-6 h-6" />
        <span className="font-semibold tracking-wide cursor-pointer" onClick={() => setView({ t: "empty" })}>TOME</span>
        <span className="pill">Library</span>
        <div className="flex-1" />
        <Button className={navBtn(view.t === "search")} onClick={() => setView({ t: "search" })}><Search className="w-4 h-4" /> Search</Button>
        <Button className={navBtn(view.t === "atlas")} onClick={() => setView({ t: "atlas" })}><Map className="w-4 h-4" /> Atlas</Button>
        <Button className={navBtn(view.t === "graph")} onClick={() => setView({ t: "graph" })}><Network className="w-4 h-4" /> Graph</Button>
        <Button className={navBtn(view.t === "memory")} onClick={() => setView({ t: "memory" })}><Brain className="w-4 h-4" /> Memory</Button>
        {isAdmin && <Button className={navBtn(view.t === "admin")} onClick={() => setView({ t: "admin" })}><Shield className="w-4 h-4" /> Admin</Button>}
        <span className="muted text-xs ml-1">{me?.email || me?.via} · {me?.role}</span>
        <Button onClick={doLogout} title="Log out"><LogOut className="w-4 h-4" /></Button>
      </header>

      <div className="flex-1 flex min-h-0">
        <Sidebar onOpenDoc={(id) => setView({ t: "doc", id })} refreshKey={refreshKey} onUpload={startUpload}
          canWrite={canWrite} selectedId={selectedFolder} onSelect={setSelectedFolder} openDocId={openDocId} />
        {view.t === "empty" && (
          <div className="flex-1 flex items-center justify-center p-8 text-center">
            <div className="muted max-w-md">
              <img src="/favicon.svg" alt="" className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <div className="text-fg font-medium mb-1">Welcome to Tome</div>
              Select a document on the left{canWrite ? ", drop a file to upload," : ""} or use Search & Atlas to explore.
              <div className="mt-2"><a className="text-acc" href="/docs" target="_blank">REST API ↗</a></div>
            </div>
          </div>
        )}
        {view.t === "doc" && <DocumentView docId={view.id} onChanged={refresh} canWrite={canWrite} />}
        {view.t === "section" && <SectionView id={view.id} onBack={() => setView({ t: "search" })} />}
        {view.t === "search" && <SearchPanel onOpenSection={(id) => setView({ t: "section", id })} />}
        {view.t === "atlas" && <AtlasPanel onOpenDoc={(id) => setView({ t: "doc", id })} />}
        {view.t === "graph" && <GraphPanel onOpenDoc={(id) => setView({ t: "doc", id })} canWrite={canWrite} />}
        {view.t === "memory" && <MemoryPanel canWrite={canWrite} />}
        {view.t === "admin" && isAdmin && <AdminPanel />}
      </div>

      <Jobs jobs={jobs} onDismiss={dismiss} />
      <Toasts />
    </div>
  );
}
