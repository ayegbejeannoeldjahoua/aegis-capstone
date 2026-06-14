import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";

export default function Chat({ profile, onHome }) {
  const [prompt, setPrompt] = useState("");
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => { if (endRef.current) endRef.current.scrollIntoView({ behavior: "smooth" }); }, [log]);

  async function send(e) {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || busy) return;
    setLog((l) => [...l, { role: "user", text }]);
    setPrompt(""); setBusy(true);
    try {
      // Governance runs in the background: the request goes through the "assistant" skill,
      // policy-checked, model-routed and budgeted under the caller's role.
      const r = await api("/v1/ask", { method: "POST", body: { prompt: text, skill_id: "assistant" } });
      const meta = [r.model && `model ${r.model}`, r.trace_id && `trace ${String(r.trace_id).slice(0, 8)}`]
        .filter(Boolean).join(" · ");
      setLog((l) => [...l, { role: "assistant", text: r.answer || "(no answer returned)", meta, docs: r.documents || [], isa: r.isa || null, trace_id: r.trace_id || null, skill_id: r.skill_id || "assistant" }]);
    } catch (e) {
      setLog((l) => [...l, { role: "error", text: `Refused: ${String(e.message || e)}` }]);
    } finally { setBusy(false); }
  }

  return (
    <div className="chat">
      <header className="topbar">
        <div className="brand">Aegis<span>AI Governance Platform</span></div>
        <div className="who">
          {profile && <span className="role-badge">{profile.role} · {profile.tenant_id}</span>}
          <button className="ghost" onClick={onHome}>← Home</button>
        </div>
      </header>
      <section className="chat-log">
        {log.length === 0 && (
          <div className="muted chat-empty">Ask anything. Your request is governed in the background by your
            role — if a policy or budget denies it, the refusal appears here.</div>
        )}
        {log.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <div className="bubble-body">{m.text}</div>
            {m.docs && m.docs.length > 0 && (
              <div className="bubble-docs">
                <small>Governed retrieval ({m.docs.length}):</small>
                <ul>{m.docs.map((d, j) => (
                  <li key={j}><small>{d.team}/{d.classification} — {d.title}</small></li>
                ))}</ul>
              </div>
            )}
            {m.isa && <DoneCriteria isa={m.isa} />}
            {m.role === "assistant" && m.trace_id && <Thumbs trace_id={m.trace_id} skill_id={m.skill_id} />}
            {m.meta && <small className="bubble-meta">{m.meta}</small>}
          </div>
        ))}
        <div ref={endRef} />
      </section>
      <form className="chat-input" onSubmit={send}>
        <input value={prompt} placeholder="Type a request…" onChange={(e) => setPrompt(e.target.value)} />
        <button type="submit" disabled={busy}>{busy ? "…" : "Send"}</button>
      </form>
    </div>
  );
}

// v1.21 PAI slice 3 -- thumbs feedback widget. Posts a binary rating and an
// optional note to /admin/turn-feedback, keyed on the audit trace_id so the
// feedback anchors to the exact governed action. Disappears once submitted.
function Thumbs({ trace_id, skill_id }) {
  const [state, setState] = React.useState({ shown: true, sent: false, rating: 0, note: "", showNote: false });
  if (!trace_id || !state.shown) return null;

  async function submit(rating) {
    try {
      await api("/admin/turn-feedback", {
        method: "POST",
        body: { trace_id, rating, note: state.note || null, skill_id },
      });
      setState({ ...state, sent: true, rating });
    } catch (e) {
      // Non-fatal: feedback is best-effort, don't block the chat on it.
      setState({ ...state, sent: true, rating, error: String(e.message || e) });
    }
  }

  if (state.sent) {
    return <div className="bubble-fb sent"><small>Thanks for the feedback.</small></div>;
  }
  return (
    <div className="bubble-fb">
      <button type="button" title="Helpful" className="fb-btn fb-up" onClick={() => submit(1)}>👍</button>
      <button type="button" title="Not helpful" className="fb-btn fb-down" onClick={() => setState({ ...state, showNote: true, rating: -1 })}>👎</button>
      {state.showNote && (
        <span className="fb-note-wrap">
          <input className="fb-note" placeholder="What was wrong? (optional)"
                 value={state.note} onChange={(e) => setState({ ...state, note: e.target.value })} />
          <button type="button" className="fb-submit" onClick={() => submit(-1)}>Send</button>
        </span>
      )}
    </div>
  );
}


// Per-task "definition of done": the Goal + binary ISC checklist returned by the backend.
// Collapsed by default; click to expand. Each ISC's evidence is shown on hover and inline when open.
function DoneCriteria({ isa }) {
  const [open, setOpen] = React.useState(false);
  if (!isa || !isa.iscs || isa.iscs.length === 0) return null;
  const allMet = isa.met === isa.total;
  return (
    <div className={`bubble-isa ${allMet ? "isa-ok" : "isa-partial"}`}>
      <button type="button" className="isa-summary" onClick={() => setOpen(!open)}>
        <span className="isa-pill">{allMet ? "✓" : "!"}</span>
        <span>Done criteria — <b>{isa.met}/{isa.total}</b> met</span>
        <span className="isa-chev">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="isa-body">
          <div className="isa-goal"><small>Goal:</small> {isa.goal}</div>
          <ul className="isa-list">
            {isa.iscs.map((c) => (
              <li key={c.id} className={c.satisfied ? "ok" : "fail"} title={c.evidence}>
                <span className="isc-mark">{c.satisfied ? "✓" : "✗"}</span>
                <span className="isc-id">{c.id}</span>
                <span className="isc-desc">{c.description}</span>
                <span className="isc-evidence">{c.evidence}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
