// Durable Processing view: every ingestion job (server-backed → survives reload),
// per-file status + stage + page progress, with download-original and open-document.
import { useEffect, useRef, useState } from "react";
import {
  Loader2, CheckCircle2, XCircle, AlertTriangle, Clock, Download, FileText, RefreshCw,
} from "lucide-react";
import { jobsApi, docs as dapi, Job } from "../lib/api";
import { Button, Pill, EmptyState, Spinner, toast } from "./ui";

function statusIcon(j: Job) {
  if (j.status === "done" && j.stage === "conflict_pending") return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
  if (j.status === "done") return <CheckCircle2 className="w-4 h-4 text-green-500" />;
  if (j.status === "error") return <XCircle className="w-4 h-4 text-red-400" />;
  if (j.status === "queued") return <Clock className="w-4 h-4 text-mut" />;
  return <Loader2 className="w-4 h-4 text-acc animate-spin" />;
}

const _ORDER = ["extract", "structure", "name", "split", "embed", "persist", "atlas"];
function fmtTimings(t?: Record<string, number> | null): string {
  if (!t || !Object.keys(t).length) return "";
  const keys = Object.keys(t).sort((a, b) => (_ORDER.indexOf(a) + 1 || 99) - (_ORDER.indexOf(b) + 1 || 99));
  const ms = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`);
  return keys.map((k) => `${k} ${ms(t[k])}`).join(" · ");
}

function stageText(j: Job): string {
  if (j.status === "done") return j.stage === "conflict_pending" ? "Needs conflict resolution"
    : j.stage === "unchanged" ? "Unchanged (duplicate)" : "Done";
  if (j.status === "error") return "Failed";
  if (j.status === "queued") return j.attempts > 0 ? `Queued (retry ${j.attempts})` : "Queued";
  return j.stage || "Processing…";
}

export function JobsPanel({ onOpenDoc }: { onOpenDoc: (id: number) => void }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [err, setErr] = useState("");
  const timer = useRef<any>(null);

  async function load() {
    try { setJobs((await jobsApi.list()).jobs); setErr(""); }
    catch (e: any) { setErr(e?.message || "failed to load jobs"); }
  }
  useEffect(() => {
    load();
    timer.current = setInterval(load, 2000);   // live updates; server-backed (reload-safe)
    return () => clearInterval(timer.current);
  }, []);

  const active = (jobs || []).filter((j) => j.status === "queued" || j.status === "running" || !["done", "error"].includes(j.status)).length;

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center gap-2 mb-1">
        <RefreshCw className="w-5 h-5 text-acc" />
        <h2 className="text-xl font-semibold">Processing</h2>
        {jobs && <span className="muted text-sm">· {jobs.length} jobs{active ? ` · ${active} active` : ""}</span>}
        <div className="flex-1" />
        <Button onClick={load}><RefreshCw className="w-4 h-4" /> Refresh</Button>
      </div>
      <p className="muted text-sm mb-4">Live status per file — split into pages, then each page processed. Updates automatically and survives a reload.</p>

      {err && <div className="text-red-400 text-sm mb-3">{err}</div>}
      {jobs === null ? <div className="muted flex items-center gap-2"><Spinner /> loading…</div>
        : jobs.length === 0 ? <EmptyState icon={<FileText className="w-10 h-10" />} title="No uploads yet"
            hint="Upload a document — its processing status will appear here." />
        : (
          <table className="w-full text-sm">
            <thead className="text-mut text-left border-b border-line">
              <tr><th className="py-2">File</th><th>Status</th><th className="w-1/3">Progress</th><th>Faith</th><th></th></tr>
            </thead>
            <tbody>
              {jobs.map((j) => {
                const pct = Math.round((j.progress || 0) * 100);
                const pages = j.pages_total ? `${Math.min(j.pages_done || 0, j.pages_total)}/${j.pages_total} pages` : "";
                const running = j.status !== "done" && j.status !== "error";
                return (
                  <tr key={j.id} className="border-b border-line/50 align-top">
                    <td className="py-2 pr-2">
                      <div className="flex items-center gap-1.5"><FileText className="w-3.5 h-3.5 text-mut shrink-0" />
                        <span className="truncate">{j.filename || `job #${j.id}`}</span></div>
                      <div className="muted text-xs">{new Date(j.created_at).toLocaleString()}</div>
                    </td>
                    <td className="py-2"><div className="flex items-center gap-1.5">{statusIcon(j)} <span>{stageText(j)}</span></div>
                      {j.error && <div className="text-red-400 text-xs mt-1 max-w-xs break-words">{j.error}</div>}</td>
                    <td className="py-2 pr-3">
                      <div className="h-1.5 bg-[#0b0e12] rounded overflow-hidden">
                        <div className={`h-full ${j.status === "error" ? "bg-red-400" : "bg-acc"} ${running && pct === 0 ? "animate-pulse w-1/4" : "transition-all"}`}
                          style={pct > 0 ? { width: `${Math.max(4, pct)}%` } : undefined} />
                      </div>
                      <div className="muted text-xs mt-1">{running && pct > 0 ? `${pct}%` : ""}{pages ? ` · ${pages}` : ""}</div>
                      {j.status === "done" && fmtTimings(j.timings_ms) &&
                        <div className="muted text-xs mt-0.5 opacity-70" title="Per-stage processing time">⏱ {fmtTimings(j.timings_ms)}</div>}
                    </td>
                    <td className="py-2">{j.faithfulness_score != null ? j.faithfulness_score.toFixed(2) : "—"}</td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {j.document_id && <button className="text-acc mr-3" onClick={() => onOpenDoc(j.document_id!)}>open</button>}
                      {j.document_id && j.source_key && (
                        <button className="text-mut hover:text-acc" title="Download original"
                          onClick={() => dapi.downloadSource(j.document_id!, j.filename || `document_${j.document_id}`).catch((e: any) => toast(e.message, "err"))}>
                          <Download className="w-4 h-4 inline" />
                        </button>)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
    </div>
  );
}
