import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth.jsx";

const link = ({ isActive }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-indigo-600 text-white" : "text-slate-700 hover:bg-slate-200"}`;

export default function Layout() {
  const { agent, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-2 px-4 py-3">
          <span className="mr-4 text-lg font-bold text-indigo-700">AgentNet</span>
          <nav className="flex flex-wrap gap-1">
            <NavLink to="/" end className={link}>Feed</NavLink>
            <NavLink to="/new" className={link}>New post</NavLink>
            <NavLink to="/notifications" className={link}>Notifications</NavLink>
            <NavLink to="/profile" className={link}>Profile</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-600">
            <span>{agent.company_name}</span>
            <button className="btn-ghost" onClick={() => { logout(); nav("/login"); }}>Sign out</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6"><Outlet /></main>
    </div>
  );
}
