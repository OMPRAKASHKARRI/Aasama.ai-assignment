import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Badge, ErrorBanner, UntrustedText, fmt, pct } from "../components/ui.jsx";

export default function Notifications() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => api.inbox().then((x) => { setItems(x); setError(null); }).catch(setError), []);
  useEffect(() => { load(); }, [load]);

  const act = (fn) => async () => { try { await fn(); await load(); } catch (e) { setError(e); } };

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">Notifications</h1>
        <button className="btn-ghost" onClick={load}>Refresh</button>
      </div>
      <p className="mb-4 text-sm text-slate-600">Posts the router judged relevant to your manifesto. Your feedback improves future routing.</p>
      <ErrorBanner error={error} />
      {items?.length === 0 && <p className="text-slate-500">Nothing yet. Relevant posts will appear here.</p>}
      <div className="space-y-3">
        {items?.map((n) => (
          <article key={n.id} className="card">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <Badge tone="indigo">relevance {pct(n.rerank_score)}</Badge>
              <Badge tone={n.delivery_status === "delivered" ? "green" : n.delivery_status === "failed" ? "red" : "amber"}>webhook {n.delivery_status}</Badge>
              {!n.opened_at && <Badge tone="amber">new</Badge>}
              <span>{fmt(n.created_at)} · from {n.post.author.company_name}</span>
            </div>
            <Link to={`/posts/${n.post.id}`} onClick={() => api.ack(n.id).catch(() => {})} className="text-lg font-semibold text-indigo-700 hover:underline">{n.post.title}</Link>
            <div className="mt-2"><UntrustedText>{n.post.content}</UntrustedText></div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {!n.opened_at && <button className="btn-ghost" onClick={act(() => api.ack(n.id))}>Mark opened</button>}
              <button className={n.feedback === "relevant" ? "btn-primary" : "btn-ghost"} onClick={act(() => api.feedback(n.id, true))}>👍 Relevant</button>
              <button className={n.feedback === "not_relevant" ? "btn-primary" : "btn-ghost"} onClick={act(() => api.feedback(n.id, false))}>👎 Not relevant</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
