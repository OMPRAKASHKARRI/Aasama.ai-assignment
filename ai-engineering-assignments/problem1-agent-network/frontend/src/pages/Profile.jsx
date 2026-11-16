import { useEffect, useState } from "react";
import { api, setApiKey } from "../api.js";
import { useAuth } from "../auth.jsx";
import { CopyField, ErrorBanner } from "../components/ui.jsx";

export default function Profile() {
  const { agent, refresh } = useAuth();
  const [f, setF] = useState({ industry: agent.industry, webhook_url: agent.webhook_url, manifesto: agent.manifesto });
  const [secret, setSecret] = useState(null);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => setF({ industry: agent.industry, webhook_url: agent.webhook_url, manifesto: agent.manifesto }), [agent]);

  const run = async (fn, ok) => { setError(null); setMsg(null); try { await fn(); setMsg(ok); } catch (e) { setError(e); } };

  return (
    <div className="space-y-4">
      <form className="card space-y-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.updateMe(f); await refresh(); }, "Profile updated and manifesto re-embedded."); }}>
        <h1 className="text-xl font-bold">{agent.company_name}</h1>
        <ErrorBanner error={error} />
        {msg && <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg}</p>}
        <div><label className="label" htmlFor="i">Industry</label><input id="i" className="input" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} required minLength={2} /></div>
        <div><label className="label" htmlFor="w">Webhook URL</label><input id="w" className="input" value={f.webhook_url} onChange={(e) => setF({ ...f, webhook_url: e.target.value })} required /></div>
        <div><label className="label" htmlFor="m">Interest manifesto</label><textarea id="m" className="input h-32" value={f.manifesto} onChange={(e) => setF({ ...f, manifesto: e.target.value })} required minLength={20} maxLength={2000} /></div>
        <button className="btn-primary">Save</button>
      </form>

      <section className="card">
        <h2 className="mb-2 font-semibold">Credentials</h2>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => run(async () => setSecret({ label: "New webhook secret", value: (await api.rotateSecret()).webhook_secret }), "Webhook secret rotated — update your receiver.")}>Rotate webhook secret</button>
          <button className="btn-ghost" onClick={() => run(async () => { const k = (await api.rotateKey()).api_key; setApiKey(k); setSecret({ label: "New API key", value: k }); }, "API key rotated — the old key no longer works.")}>Rotate API key</button>
        </div>
        {secret && <div className="mt-3"><CopyField label={`${secret.label} (shown once)`} value={secret.value} /></div>}
      </section>
    </div>
  );
}
