import { Link } from "react-router-dom";
import { Badge, fmt } from "./ui.jsx";

export default function PostCard({ post }) {
  return (
    <article className="card">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="font-semibold text-slate-700">{post.author.company_name}</span>
        <Badge tone="indigo">{post.author.industry}</Badge>
        {post.status === "draft" && <Badge tone="amber">draft</Badge>}
        <span>{fmt(post.published_at || post.created_at)}</span>
      </div>
      <Link to={`/posts/${post.id}`} className="text-lg font-semibold text-indigo-700 hover:underline">{post.title}</Link>
      <p className="mt-1 line-clamp-3 whitespace-pre-wrap break-words text-sm text-slate-700">{post.content}</p>
      <div className="mt-2 flex flex-wrap gap-1">{post.tags.map((t) => <Badge key={t}>#{t}</Badge>)}</div>
    </article>
  );
}
