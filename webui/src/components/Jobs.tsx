import { Loader2, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

export interface JobInfo {
  name: string;
  stage: string;
  status: string;     // uploading | queued | running | done | error
  progress: number;   // 0..1
  error?: string;
}

// Human-readable pipeline stage labels (match tome/pipeline/run.py).
const STAGE_LABEL: Record<string, string> = {
  upload: "Uploading file…",
  queued: "Queued",
  running: "Processing…",
  extract: "Extracting text (OCR)",
  structure: "Structuring",
  vision: "Analyzing images",
  name: "Naming & placement",
  split: "Splitting into parts",
  index: "Indexing for search",
  atlas: "Updating Atlas",
  done: "Done",
  unchanged: "Unchanged (duplicate)",
  conflict_pending: "Conflict — needs resolution",
  error: "Error",
};

export function Jobs({ jobs, onDismiss }: { jobs: Record<number, JobInfo>; onDismiss: (id: number) => void }) {
  const entries = Object.entries(jobs);
  if (!entries.length) return null;
  return (
    <div className="fixed bottom-4 right-4 z-40 w-80 space-y-2">
      {entries.map(([id, j]) => {
        const done = j.status === "done";
        const err = j.status === "error";
        const conflict = j.stage === "conflict_pending";
        const pct = Math.round((j.progress || 0) * 100);
        return (
          <div key={id} className="card shadow-lg border-line">
            <div className="flex items-center gap-2 text-sm">
              {err ? <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                : conflict ? <AlertTriangle className="w-4 h-4 text-yellow-500 shrink-0" />
                : done ? <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                : <Loader2 className="w-4 h-4 text-acc animate-spin shrink-0" />}
              <span className="truncate flex-1" title={j.name}>{j.name}</span>
              <button className="text-mut hover:text-fg shrink-0" onClick={() => onDismiss(Number(id))}>✕</button>
            </div>
            <div className="muted text-xs mt-1">
              {STAGE_LABEL[j.stage] || STAGE_LABEL[j.status] || j.stage || j.status}
              {!done && !err && pct > 0 && <span className="ml-1">· {pct}%</span>}
            </div>
            {!done && !err && (
              <div className="h-1.5 bg-[#0b0e12] rounded mt-1.5 overflow-hidden">
                <div className={`h-full bg-acc transition-all duration-500 ${pct === 0 ? "animate-pulse w-1/4" : ""}`}
                     style={pct > 0 ? { width: `${Math.max(6, pct)}%` } : undefined} />
              </div>
            )}
            {err && j.error && <div className="text-red-400 text-xs mt-1 break-words">{j.error}</div>}
          </div>
        );
      })}
    </div>
  );
}
