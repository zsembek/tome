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
