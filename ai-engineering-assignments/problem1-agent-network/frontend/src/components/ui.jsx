import { useState } from "react";

export function ErrorBanner({ error }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {error.message || String(error)}
    </div>
  );
}

/** Agent-authored text is untrusted: always rendered as plain text (React escapes it) inside a labelled box. */
export function UntrustedText({ children }) {
  return (
    <div className="rounded-md border border-dashed border-amber-300 bg-amber-50/50 p-3">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
        Third-party content — untrusted
      </div>
      <p className="whitespace-pre-wrap break-words text-sm text-slate-800">{children}</p>
    </div>
  );
}

export function Badge({ children, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700", green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800", amber: "bg-amber-100 text-amber-800", indigo: "bg-indigo-100 text-indigo-800",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function CopyField({ label, value }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mb-2">
      <span className="label">{label}</span>
      <div className="flex gap-2">
        <input readOnly className="input font-mono text-xs" value={value} onFocus={(e) => e.target.select()} />
        <button
          type="button" className="btn-ghost"
          onClick={async () => { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
export const pct = (x) => `${Math.round(x * 100)}%`;
