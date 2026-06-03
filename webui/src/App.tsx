import { useEffect, useState } from "react";
import { Search, Map, Shield, LogOut } from "lucide-react";
import { api, auth, AuthStatus, Me } from "./lib/api";
import { Button } from "./components/ui";
import { Login } from "./components/Login";
import { Sidebar } from "./components/Sidebar";
import { DocumentView } from "./components/DocumentView";
import { SearchPanel, AtlasPanel, AdminPanel, SectionView } from "./components/Panels";
import { Jobs, JobInfo } from "./components/Jobs";

type View =
  | { t: "empty" } | { t: "doc"; id: number } | { t: "section"; id: number }
  | { t: "search" } | { t: "atlas" } | { t: "admin" };

export default function App() {
  const [view, setView] = useState<View>({ t: "empty" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [jobs, setJobs] = useState<Record<number, JobInfo>>({});
  const [booted, setBooted] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const refresh = () => setRefreshKey((k) => k + 1);

  async function checkAuth() {
    try {
      const st = await auth.status();
      setStatus(st);
      if (st.open_mode) {
        setMe({ email: null, role: "admin", scopes: ["read", "write", "admin"], via: "open" });
        setBooted(true); return;
      }
      try { setMe(await auth.me()); }
      catch { setMe(null); }
    } catch { setMe(null); }
    setBooted(true);
  }
  useEffect(() => { checkAuth(); }, []);

  function dismiss(id: number) {
    setJobs((j) => { const c = { ...j }; delete c[id]; return c; });
  }

  function pollJob(jobId: number, name: string) {
    const t = setInterval(async () => {
      try {
        const j = await api.get(`/jobs/${jobId}`);
        setJobs((s) => ({ ...s, [jobId]: { name, stage: j.stage || j.status, status: j.status, progress: j.progress ?? 0, error: j.error } }));
        if (j.status === "done" || j.status === "error") {
          clearInterval(t); refresh();
          setTimeout(() => dismiss(jobId), j.status === "error" ? 15000 : 5000);
        }
      } catch { clearInterval(t); }
    }, 1200);
  }

  // Upload with progress shown FROM THE START (before job_id is known), then poll stages.
  async function startUpload(file: File, folderPath?: string) {
    const tmp = -Date.now();
    setJobs((j) => ({ ...j, [tmp]: { name: file.name, stage: "upload", status: "uploading", progress: 0 } }));
    try {
      const r = await api.upload(file, folderPath);
      setJobs((j) => { const c = { ...j }; delete c[tmp]; c[r.job_id] = { name: file.name, stage: "queued", status: "queued", progress: 0 }; return c; });
      pollJob(r.job_id, file.name);
    } catch (e: any) {
      setJobs((j) => ({ ...j, [tmp]: { name: file.name, stage: "error", status: "error", progress: 0, error: e?.message || "upload failed" } }));
      setTimeout(() => dismiss(tmp), 15000);
    }
  }

  async function doLogout() { await auth.logout(); setMe(null); setView({ t: "empty" }); }

  if (!booted) return <div className="h-full flex items-center justify-center muted">…</div>;
  if (!me && status) return <Login status={status} onAuthed={() => { setBooted(false); checkAuth(); }} />;

  const canWrite = !!me?.scopes.includes("write");
  const isAdmin = !!me?.scopes.includes("admin");

  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-line">
        <img src="/favicon.svg" alt="Tome" className="w-6 h-6" />
        <span className="font-semibold tracking-wide">TOME</span>
        <span className="pill">Library</span>
        <div className="flex-1" />
        <Button onClick={() => setView({ t: "search" })}><Search className="w-4 h-4" /> Search</Button>
        <Button onClick={() => setView({ t: "atlas" })}><Map className="w-4 h-4" /> Atlas</Button>
        {isAdmin && <Button onClick={() => setView({ t: "admin" })}><Shield className="w-4 h-4" /> Admin</Button>}
        <span className="muted text-xs ml-1">{me?.email || me?.via} · {me?.role}</span>
        <Button onClick={doLogout} title="Log out"><LogOut className="w-4 h-4" /></Button>
      </header>

      <div className="flex-1 flex min-h-0">
        <Sidebar onOpenDoc={(id) => setView({ t: "doc", id })} refreshKey={refreshKey} onUpload={startUpload} canWrite={canWrite} />
        {view.t === "empty" && <div className="flex-1 p-8 muted">Select a document on the left{canWrite ? ", upload a file," : ""} or use search. <a className="text-acc" href="/docs" target="_blank">API</a></div>}
        {view.t === "doc" && <DocumentView docId={view.id} onChanged={refresh} canWrite={canWrite} />}
        {view.t === "section" && <SectionView id={view.id} onBack={() => setView({ t: "search" })} />}
        {view.t === "search" && <SearchPanel onOpenSection={(id) => setView({ t: "section", id })} />}
        {view.t === "atlas" && <AtlasPanel />}
        {view.t === "admin" && isAdmin && <AdminPanel />}
      </div>

      <Jobs jobs={jobs} onDismiss={dismiss} />
    </div>
  );
}
