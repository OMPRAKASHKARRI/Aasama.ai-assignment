import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, csv } from "../api.js";
import { ErrorBanner } from "../components/ui.jsx";

export default function NewPost() {
  const nav = useNavigate();
  const [f, setF] = useState({ title: "", content: "", tags: "", targets: "", publish: true });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const post = await api.createPost({ title: f.title, content: f.content, tags: csv(f.tags), target_industries: csv(f.targets), publish: f.publish });
      nav(`/posts/${post.id}`);
    } catch (err) { setError(err); } finally { setBusy(false); }
  };

  return (
    <form className="card space-y-3" onSubmit={submit}>
      <h1 className="text-xl font-bold">New post</h1>
      <ErrorBanner error={error} />
      <div><label className="label" htmlFor="t">Title</label><input id="t" className="input" value={f.title} onChange={set("title")} required minLength={3} maxLength={200} /></div>
      <div><label className="label" htmlFor="c">Content</label><textarea id="c" className="input h-40" value={f.content} onChange={set("content")} required minLength={10} maxLength={5000} /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label" htmlFor="tg">Tags (comma separated)</label><input id="tg" className="input" value={f.tags} onChange={set("tags")} placeholder="zero-trust, compliance" /></div>
        <div><label className="label" htmlFor="ti">Only notify industries (optional)</label><input id="ti" className="input" value={f.targets} onChange={set("targets")} placeholder="Fintech, Healthcare" /></div>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.publish} onChange={set("publish")} /> Publish now and notify relevant agents</label>
      <button className="btn-primary" disabled={busy}>{f.publish ? "Publish" : "Save draft"}</button>
    </form>
  );
}
