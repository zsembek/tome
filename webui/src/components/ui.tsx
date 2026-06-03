// Lightweight shadcn-style primitives on Tailwind (no radix dependencies).
import React from "react";

export function Button({ className = "", primary = false, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean }) {
  return <button className={`btn ${primary ? "btn-primary" : ""} ${className}`} {...p} />;
}

export function Input(p: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...p} />;
}

export function Pill({ children }: { children: React.ReactNode }) {
  return <span className="pill">{children}</span>;
}

export function Card({ children, className = "", onClick }: { children: React.ReactNode; className?: string; onClick?: () => void }) {
  return <div className={`card ${onClick ? "cursor-pointer hover:border-acc" : ""} ${className}`} onClick={onClick}>{children}</div>;
}

export function Spinner({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-90" d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function EmptyState({ icon, title, hint }: { icon?: React.ReactNode; title: string; hint?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6 text-mut">
      {icon && <div className="mb-3 opacity-60">{icon}</div>}
      <div className="text-fg font-medium">{title}</div>
      {hint && <div className="text-sm mt-1 max-w-sm">{hint}</div>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: React.ReactNode }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-line mb-4">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`px-3 py-2 text-sm -mb-px border-b-2 transition-colors ${active === t.id ? "border-acc text-fg" : "border-transparent text-mut hover:text-fg"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// Click-to-open dropdown menu (closes on outside click / item select).
export function Menu({ trigger, children }: { trigger: React.ReactNode; children: (close: () => void) => React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <div className="relative inline-block" ref={ref}>
      <span onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}>{trigger}</span>
      {open && (
        <div className="absolute right-0 mt-1 z-50 min-w-[160px] bg-panel border border-line rounded-md shadow-lg py-1 text-sm"
             onClick={(e) => e.stopPropagation()}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ onClick, children, danger = false }: { onClick: () => void; children: React.ReactNode; danger?: boolean }) {
  return (
    <button className={`w-full text-left px-3 py-1.5 hover:bg-[#1e252e] ${danger ? "text-red-400" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

// ── Toasts (module-level emitter; render <Toasts/> once at the app root) ──
type Toast = { id: number; kind: "ok" | "err" | "info"; msg: string };
let _toastSeq = 1;
const _listeners = new Set<(t: Toast[]) => void>();
let _toasts: Toast[] = [];
function _emit() { _listeners.forEach((l) => l([..._toasts])); }
export function toast(msg: string, kind: "ok" | "err" | "info" = "ok") {
  const t = { id: _toastSeq++, kind, msg };
  _toasts = [..._toasts, t];
  _emit();
  setTimeout(() => { _toasts = _toasts.filter((x) => x.id !== t.id); _emit(); }, kind === "err" ? 6000 : 3000);
}
export function Toasts() {
  const [items, setItems] = React.useState<Toast[]>([]);
  React.useEffect(() => { _listeners.add(setItems); return () => { _listeners.delete(setItems); }; }, []);
  if (!items.length) return null;
  return (
    <div className="fixed top-4 right-4 z-[60] space-y-2 w-80">
      {items.map((t) => (
        <div key={t.id} className={`card text-sm shadow-lg border-l-4 ${t.kind === "err" ? "border-l-red-400" : t.kind === "info" ? "border-l-acc" : "border-l-green-500"}`}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide = false }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className={`bg-panel border border-line rounded-lg p-4 max-h-[85vh] overflow-auto ${wide ? "w-[860px]" : "w-[520px]"}`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold">{title}</h3>
          <button className="text-mut hover:text-fg" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
