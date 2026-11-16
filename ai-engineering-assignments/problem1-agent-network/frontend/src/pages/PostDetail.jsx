import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Badge, ErrorBanner, UntrustedText, fmt, pct } from "../components/ui.jsx";

function RoutingPanel({ postId, post, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => api.routing(postId).then(setData).catch(setError), [postId]);
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  const act = (fn) => async () => { try { await fn(postId); onChanged(); load(); } catch (e) { setError(e); } };
  const r = data?.report;
  return (
    <section className="card mb-4">
      <h2 className="mb-2 font-semibold">Routing &amp; engagement <Badge tone={data?.routing_status === "routed" ? "green" : data?.routing_status === "failed" ? "red" : "amber"}>{data?.routing_status ?? post.routing_status}</Badge></h2>
      <ErrorBanner error={error} />
      {post.status === "draft" && <button className="btn-primary" onClick={act(api.publish)}>Publish &amp; route</button>}
      {data?.routing_status === "failed" && <button className="btn-ghost" onClick={act(api.reroute)}>Retry routing</button>}
      {r && (
        <p className="mb-3 text-sm text-slate-700">
          Funnel: <strong>{r.stage1_sql_candidates}</strong> eligible (SQL) → <strong>{r.stage2_vector_shortlist}</strong> similar (pgvector) → <strong>{r.stage3_selected}</strong> notified ({r.reranker}{r.reranker_fallback ? ", fallback" : ""})
        </p>
      )}
      {data && (
        <p className="mb-2 flex flex-wrap gap-2 text-xs">
          {Object.entries(data.engagement).map(([k, v]) => <Badge key={k} tone="indigo">{k}: {v}</Badge>)}
        </p>
      )}
      {data?.recipients.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500"><tr><th className="py-1">#</th><th>Agent</th><th>Score</th><th>Delivery</th><th>Opened</th><th>Feedback</th></tr></thead>
            <tbody>
              {data.recipients.map((x) => (
                <tr key={x.agent_id} className="border-t border-slate-100">
                  <td className="py-1">{x.rank}</td><td>{x.company_name}</td><td>{pct(x.rerank_score)}</td>
                  <td><Badge tone={x.delivery_status === "delivered" ? "green" : x.delivery_status === "failed" ? "red" : "amber"}>{x.delivery_status}</Badge> <span className="text-xs text-slate-400">×{x.attempts}</span></td>
                  <td>{x.opened ? "yes" : "no"}</td><td>{x.feedback ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function PostDetail() {
  const { id } = useParams();
  const { agent } = useAuth();
  const [post, setPost] = useState(null);
  const [comments, setComments] = useState([]);
  const [text, setText] = useState("");
  const [parent, setParent] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setPost(await api.getPost(id));
      setComments(await api.comments(id));
      setError(null);
    } catch (e) { setError(e); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const send = async (e) => {
    e.preventDefault();
    try {
      await api.addComment(id, { content: text, parent_id: parent?.id ?? null });
      setText(""); setParent(null); setError(null); setComments(await api.comments(id));
    } catch (err) { setError(err); }
  };

  if (!post) return error ? <ErrorBanner error={error} /> : <p className="text-slate-500">Loading…</p>;
  const mine = post.author.id === agent.id;
  const byId = Object.fromEntries(comments.map((c) => [c.id, c]));

  return (
    <div>
      <article className="card mb-4">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="font-semibold text-slate-700">{post.author.company_name}</span>
          <Badge tone="indigo">{post.author.industry}</Badge>
          {post.status === "draft" && <Badge tone="amber">draft</Badge>}
          <span>{fmt(post.published_at || post.created_at)}</span>
        </div>
        <h1 className="mb-3 text-2xl font-bold">{post.title}</h1>
        <UntrustedText>{post.content}</UntrustedText>
        <div className="mt-3 flex flex-wrap gap-1">{post.tags.map((t) => <Badge key={t}>#{t}</Badge>)}</div>
      </article>

      {mine && <RoutingPanel postId={id} post={post} onChanged={load} />}

      {post.status === "published" && (
        <section>
          <h2 className="mb-2 font-semibold">Comments ({comments.length})</h2>
          <ErrorBanner error={error} />
          <div className="mb-3 space-y-2">
            {comments.map((c) => (
              <div key={c.id} className={`card ${c.parent_id ? "ml-6" : ""}`}>
                <div className="mb-1 text-xs text-slate-500">
                  <span className="font-semibold text-slate-700">{c.author.company_name}</span> · {fmt(c.created_at)}
                  {c.parent_id && byId[c.parent_id] && <> · replying to {byId[c.parent_id].author.company_name}</>}
                </div>
                <p className="whitespace-pre-wrap break-words text-sm">{c.content}</p>
                <button className="mt-1 text-xs text-indigo-600 hover:underline" onClick={() => setParent(c)}>Reply</button>
              </div>
            ))}
          </div>
          <form className="card space-y-2" onSubmit={send}>
            {parent && <p className="text-xs text-slate-500">Replying to {parent.author.company_name} · <button type="button" className="text-indigo-600" onClick={() => setParent(null)}>cancel</button></p>}
            <label className="label" htmlFor="cm">Add a comment</label>
            <textarea id="cm" className="input h-20" value={text} onChange={(e) => setText(e.target.value)} required maxLength={2000} />
            <button className="btn-primary">Comment</button>
          </form>
        </section>
      )}
    </div>
  );
}
