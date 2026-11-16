import { useEffect, useState } from "react";
import { api } from "../api.js";
import PostCard from "../components/PostCard.jsx";
import { ErrorBanner } from "../components/ui.jsx";

export default function Feed() {
  const [filters, setFilters] = useState({ tag: "", industry: "", mine: false });
  const [posts, setPosts] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    setPosts(null);
    api.listPosts({ ...filters, limit: 50 })
      .then((p) => live && (setPosts(p), setError(null)))
      .catch((e) => live && setError(e));
    return () => { live = false; };
  }, [filters]);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div><label className="label" htmlFor="tag">Tag</label><input id="tag" className="input w-40" value={filters.tag} onChange={(e) => setFilters({ ...filters, tag: e.target.value })} placeholder="e.g. logistics" /></div>
        <div><label className="label" htmlFor="ind">Author industry</label><input id="ind" className="input w-48" value={filters.industry} onChange={(e) => setFilters({ ...filters, industry: e.target.value })} /></div>
        <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={filters.mine} onChange={(e) => setFilters({ ...filters, mine: e.target.checked })} /> My posts (incl. drafts)</label>
      </div>
      <ErrorBanner error={error} />
      {posts === null && !error && <p className="text-slate-500">Loading…</p>}
      {posts?.length === 0 && <p className="text-slate-500">No posts found.</p>}
      <div className="space-y-3">{posts?.map((p) => <PostCard key={p.id} post={p} />)}</div>
    </div>
  );
}
