import React, { useState } from "react";
import { api } from "../api/client.js";

export default function TestConsole() {
  const [prompt, setPrompt] = useState("What is known about widget defects in Q1?");
  const [model, setModel] = useState("");
  const [inject, setInject] = useState(false);
  const [res, setRes] = useState(null);
  const [trace, setTrace] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [eraseId, setEraseId] = useState("");
  const [eraseRes, setEraseRes] = useState("");

  async function ask(e) {
    e.preventDefault();
    setBusy(true); setErr(""); setRes(null); setTrace(null);
    try {
      const body = { prompt, inject_tool_output: inject };
      if (model) body.model = model;
      const r = await api("/v1/ask", { method: "POST", body });
      setRes(r);
      if (r.trace_id) {
        try { const t = await api(`/v1/audit/trace/${r.trace_id}`); setTrace(t.events || []); } catch (_) {}
      }
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function erase(e) {
    e.preventDefault(); setEraseRes("");
    try { const r = await api(`/v1/memory/${eraseId}`, { method: "DELETE" }); setEraseRes(JSON.stringify(r)); }
    catch (e) { setEraseRes("Refused: " + String(e.message || e)); }
  }

  return (
    <div className="grid2">
      <div className="card">
        <h2>Ask (governed)</h2>
        <form onSubmit={ask}>
          <label>Prompt
            <textarea rows="4" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </label>
          <label>Model (optional)
            <input value={model} placeholder="ollama/llama3.1:8b" onChange={(e) => setModel(e.target.value)} />
          </label>
          <label className="row">
            <input type="checkbox" checked={inject} onChange={(e) => setInject(e.target.checked)} />
            Inject untrusted tool instruction (containment demo)
          </label>
          <button type="submit" disabled={busy}>{busy ? "Running…" : "Run"}</button>
        </form>
        {err && <div className="error">{err}</div>}
        {res && (
          <div className="answer">
            <h3>Answer</h3>
            <p>{res.answer}</p>
            <small>model {res.model} · {res.summary_words} words · trace {res.trace_id}</small>
          </div>
        )}
        <h3 style={{ marginTop: 16 }}>Erase memory (right-to-erasure)</h3>
        <form onSubmit={erase} className="inline">
          <input value={eraseId} placeholder="memory id (from an answer above)" onChange={(e) => setEraseId(e.target.value)} />
          <button type="submit">Erase</button>
        </form>
        {eraseRes && <small className="muted">{eraseRes}</small>}
      </div>

      <div className="card">
        <h2>Audit trace</h2>
        {!trace && <small className="muted">Run a request to see its per-action policy decisions.</small>}
        {trace && (
          <table>
            <thead><tr><th>Action</th><th>Resource</th><th>Decision</th></tr></thead>
            <tbody>
              {trace.map((ev) => (
                <tr key={ev.sequence_id} className={ev.decision === "deny" ? "deny" : ""}>
                  <td>{ev.action}</td><td>{ev.resource}</td><td>{ev.decision}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
