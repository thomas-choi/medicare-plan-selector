// /admin (DESIGN §7): served behind nginx basic auth + IP allowlist, which also adds the X-Admin-Gate header.
// Shows redacted fields only. Every request is audited server-side.
import { useCallback, useEffect, useState } from "react";

interface Item {
  id: number;
  created_at: string;
  kind: string;
  mode: string;
  linked: boolean;
  rating: number | null;
  thumbs: number | null;
  chosen_plan_key: string | null;
  text_redacted: string | null;
  prompt_version: string;
  model_id: string;
  triage_status: string;
}

interface Summary {
  thumbs: { up: number; down: number; up_rate: number | null };
  outcomes: Record<string, number>;
  llm_usage: { mode: string; cost_usd: number; tokens: number }[];
}

const STATUSES = ["new", "accepted", "test-added", "closed"];

export function Admin() {
  const [items, setItems] = useState<Item[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const q = new URLSearchParams();
    if (kind) q.set("kind", kind);
    if (status) q.set("status", status);
    const [l, s] = await Promise.all([fetch(`/api/admin/feedback?${q}`), fetch("/api/admin/summary")]);
    if (!l.ok || !s.ok) {
      setError(`Admin API unavailable (${l.status}). It only works behind the admin gate.`);
      return;
    }
    setError(null);
    setItems((await l.json()).items);
    setSummary(await s.json());
  }, [kind, status]);

  useEffect(() => {
    void load();
  }, [load]);

  async function triage(id: number, triage_status: string) {
    await fetch(`/api/admin/feedback/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ triage_status }),
    });
    void load();
  }

  return (
    <main className="admin">
      <h1>Feedback admin</h1>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {summary && (
        <section className="card">
          <p>
            👍 {summary.thumbs.up} · 👎 {summary.thumbs.down}
            {summary.thumbs.up_rate !== null && ` · ${Math.round(summary.thumbs.up_rate * 100)}% helpful`}
          </p>
          <p>
            Outcomes:{" "}
            {Object.entries(summary.outcomes)
              .map(([k, v]) => `${k}: ${v}`)
              .join(", ") || "none"}
          </p>
          <p>
            LLM spend (30 days):{" "}
            {summary.llm_usage.map((u) => `${u.mode} $${u.cost_usd.toFixed(2)}`).join(", ") || "none"}
          </p>
        </section>
      )}
      <div className="row">
        <label>
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All</option>
            <option value="recommendation_rating">Ratings</option>
            <option value="session_outcome">Outcomes</option>
            <option value="general">General</option>
            <option value="bug">Bugs</option>
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <a href="/api/admin/feedback/export?format=csv">Export CSV (redacted)</a>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>When</th>
              <th>Kind</th>
              <th>Mode</th>
              <th>Rating</th>
              <th>Text (redacted)</th>
              <th>Prompt / model</th>
              <th>Triage</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td>{i.id}</td>
                <td>{i.created_at}</td>
                <td>{i.kind}</td>
                <td>
                  {i.mode}
                  {i.linked ? "" : " (unlinked)"}
                </td>
                <td>
                  {i.thumbs === 1 ? "👍" : i.thumbs === -1 ? "👎" : ""} {i.rating ?? ""}{" "}
                  {i.chosen_plan_key ?? ""}
                </td>
                <td>{i.text_redacted}</td>
                <td>
                  {i.prompt_version} / {i.model_id}
                </td>
                <td>
                  <select
                    aria-label={`Triage ${i.id}`}
                    value={i.triage_status}
                    onChange={(e) => triage(i.id, e.target.value)}
                  >
                    {STATUSES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
