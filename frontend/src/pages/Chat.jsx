import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  FileText,
  Gavel,
  Heart,
  Home as HomeIcon,
  LayoutDashboard,
  MessageSquare,
  Paperclip,
  Plus,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { api } from "../api/client.js";
import {
  AegisBadge,
  AegisButton,
  EmptyPanel,
  ShellTopBar,
  cx,
} from "../components/figma/AegisPrimitives.jsx";
import { assistantNavItems } from "../homeModel.js";

const NAV_ICONS = {
  home: HomeIcon,
  chat: MessageSquare,
  dashboard: LayoutDashboard,
  audit: FileText,
  governance: ShieldCheck,
  console: Settings,
  finops: CircleDollarSign,
  values: Heart,
};

function formatScore(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : null;
}

function formatReason(value) {
  if (!value) return null;
  return String(value).replaceAll("_", " ");
}

function retrievalDoc(doc) {
  const namespace = doc?.namespace || doc?.team || doc?.source || "unknown";
  const classification = doc?.classification || "unclassified";
  return {
    title: doc?.title || doc?.doc_id || namespace,
    namespace,
    classification,
    tenant: doc?.tenant_id || null,
    score: formatScore(doc?.score ?? doc?.similarity),
    reason: formatReason(doc?.retrieval_reason || doc?.reason),
    isInjectionCanary: Boolean(doc?.is_injection_canary),
    canaryType: formatReason(doc?.canary_type),
  };
}

function securityFinding(finding) {
  return {
    title: finding?.title || finding?.memory_id || "Retrieved content",
    namespace: finding?.namespace || "unknown",
    classification: finding?.classification || "unclassified",
    decision: finding?.decision || "warn",
    action: formatReason(finding?.action),
    reason: formatReason(finding?.detail || finding?.reason),
    canaryType: formatReason(finding?.canary_type),
  };
}

export default function Chat({ profile, claims = {}, onHome, onLogout, go }) {
  const [prompt, setPrompt] = useState("");
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const navItems = assistantNavItems(profile || {});

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
      const findings = Array.isArray(r.visible_inspector_findings)
        ? r.visible_inspector_findings
        : (Array.isArray(r.inspector_findings) ? r.inspector_findings.filter((f) => f?.display !== false) : []);
      setLog((l) => [...l, { role: "assistant", text: r.answer || "(no answer returned)", meta, docs: Array.isArray(r.documents) ? r.documents : [], findings, governance: r.governance_flow || null, isa: r.isa || null, trace_id: r.trace_id || null, skill_id: r.skill_id || "assistant" }]);
    } catch (e) {
      setLog((l) => [...l, { role: "error", text: `Refused: ${String(e.message || e)}` }]);
    } finally { setBusy(false); }
  }

  function openNav(item) {
    if (item.target === "home") onHome?.();
    else if (item.target === "chat") return;
    else if (item.target === "values") go?.("console", "values");
    else if (item.target === "console") go?.("console");
    else go?.("console", item.target);
  }

  function newChat() {
    setLog([]);
    setPrompt("");
  }

  return (
    <div className="chat aegis-chat">
      <ShellTopBar onBack={onHome} profile={profile} claims={claims} onLogout={onLogout} section="Chat / Governed Assistant" />
      <div className="aegis-chat-body">
        <aside className="aegis-chat-nav" aria-label="AI Assistant navigation">
          <nav>
            {navItems.map((item) => {
              const Icon = NAV_ICONS[item.id] || Gavel;
              const active = item.id === "chat";
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cx("aegis-chat-nav-item", active && "active")}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.label}
                  title={item.label}
                  onClick={() => openNav(item)}
                >
                  <Icon size={15} aria-hidden="true" />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        <aside className="aegis-chat-conversations" aria-label="Conversations">
          <div className="aegis-chat-conversations-head">
            <strong>Conversations</strong>
            <button type="button" className="aegis-icon-button" aria-label="New chat" onClick={newChat}>
              <Plus size={14} />
            </button>
          </div>
          <label className="aegis-chat-search">
            <Search size={13} />
            <input type="search" placeholder="Search conversations" aria-label="Search conversations" />
          </label>
          <div className="aegis-chat-conversation-empty">
            <MessageSquare size={16} />
            <span>No saved conversations yet</span>
          </div>
        </aside>

        <main className="aegis-chat-main">
          <div className="aegis-chat-main-head">
            <div>
              <h1>AI Assistant (Chat)</h1>
              <p>{profile?.role || "role pending"} · {profile?.tenant_id || "tenant pending"}</p>
            </div>
            <AegisButton type="button" variant="ghost" icon={Plus} onClick={newChat}>New chat</AegisButton>
          </div>
          <div className="aegis-chat-policybar">
            <ShieldCheck size={12} />
            <span>active controls</span>
            <AegisBadge>PII redaction</AegisBadge>
            <AegisBadge>model routing</AegisBadge>
            <AegisBadge>FinOps guard</AegisBadge>
            <div className="aegis-chat-model">
              <Sparkles size={12} />
              <span>assistant skill</span>
            </div>
          </div>

          <section className="chat-log aegis-chat-log" aria-live="polite">
            {log.length === 0 && (
              <EmptyPanel icon={MessageSquare} title="Start a governed conversation">
                Ask Aegis a question. Requests are policy-checked, model-routed, budgeted and audited under your role.
              </EmptyPanel>
            )}
            {log.map((m, i) => (
              <div key={i} className={cx("aegis-bubble-row", m.role === "user" && "from-user", m.role === "error" && "from-error")}>
                {m.role !== "user" && (
                  <div className={cx("aegis-bubble-avatar", m.role === "error" && "error")}>
                    {m.role === "error" ? <AlertTriangle size={13} /> : <Sparkles size={13} />}
                  </div>
                )}
                <article className={`bubble aegis-bubble ${m.role}`}>
                  <div className="bubble-body">{m.text}</div>
                  {m.governance && <GovernanceFlow flow={m.governance} />}
                  {m.findings && m.findings.length > 0 && <SecurityFindings findings={m.findings} />}
                  {m.docs && m.docs.length > 0 && <RetrievalPanel docs={m.docs} />}
                  {m.isa && <DoneCriteria isa={m.isa} />}
                  {m.role === "assistant" && m.trace_id && <Thumbs trace_id={m.trace_id} skill_id={m.skill_id} />}
                  {m.meta && <small className="bubble-meta">{m.meta}</small>}
                </article>
              </div>
            ))}
            <div ref={endRef} />
          </section>

          <form className="chat-input aegis-chat-input" onSubmit={send}>
            <div className="aegis-composer">
              <Paperclip size={14} />
              <input value={prompt} placeholder="Ask the governed assistant..." onChange={(e) => setPrompt(e.target.value)} />
              <span className="aegis-enter-hint">Enter</span>
              <AegisButton type="submit" disabled={busy} icon={Send}>
                {busy ? "Sending" : "Send"}
              </AegisButton>
            </div>
            <div className="aegis-composer-meta">
              <span><span className="aegis-live-dot" /> governed · audited</span>
              <span>skill_id assistant</span>
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}

function GovernanceFlow({ flow }) {
  const controls = Array.isArray(flow?.controls) ? flow.controls : [];
  const values = Array.isArray(flow?.active_values) ? flow.active_values : [];
  const constraints = Array.isArray(flow?.constraints_detected) ? flow.constraints_detected : [];
  if (controls.length === 0 && values.length === 0) return null;
  return (
    <div className="bubble-docs aegis-bubble-docs aegis-governance-flow">
      <small><ShieldCheck size={11} /> Governance flow</small>
      <ol className="retrieval-list">
        {controls.map((c, j) => (
          <li key={`${c.label}-${j}`} className="retrieval-item">
            <span className="retrieval-title">
              {c.label}
              {c.status && <span className="retrieval-canary-badge">{formatReason(c.status)}</span>}
            </span>
            <span className="retrieval-meta">
              {c.detail && <span>{formatReason(c.detail)}</span>}
              {Array.isArray(c.constraints) && c.constraints.map((name) => (
                <span key={`${c.label}-${name}`}>{formatReason(name)}</span>
              ))}
            </span>
          </li>
        ))}
        {values.map((v, j) => (
          <li key={`${v.scope}-${v.title}-${j}`} className="retrieval-item">
            <span className="retrieval-title">
              {v.title || "Active value"}
              {v.scope && <span className="retrieval-canary-badge">{formatReason(v.scope)}</span>}
            </span>
            {(v.rule || constraints.length > 0) && (
              <span className="retrieval-meta">
                {v.rule && <span>{v.rule}</span>}
                {constraints.map((name) => <span key={`${v.title}-${name}`}>{formatReason(name)}</span>)}
              </span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function SecurityFindings({ findings }) {
  const rows = (findings || []).filter((f) => f?.display !== false).map(securityFinding);
  if (rows.length === 0) return null;
  return (
    <div className="bubble-docs aegis-bubble-docs aegis-security-findings">
      <small><AlertTriangle size={11} /> Security findings ({rows.length})</small>
      <ol className="retrieval-list">
        {rows.map((f, j) => (
          <li key={`${f.title}-${f.namespace}-${f.classification}-${j}`} className="retrieval-item security-finding-item">
            <span className="security-finding-title">
              {f.title}
              <span className="retrieval-canary-badge">{f.decision}</span>
            </span>
            <span className="retrieval-meta">
              <span>{f.namespace} / {f.classification}</span>
              {f.canaryType && <span>{f.canaryType}</span>}
              {f.action && <span>{f.action}</span>}
              {f.reason && <span>{f.reason}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function RetrievalPanel({ docs }) {
  const seen = new Set();
  const rows = docs.map(retrievalDoc).filter((d) => {
    const key = `${d.title}|${d.namespace}|${d.classification}|${d.tenant || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return (
    <div className="bubble-docs aegis-bubble-docs">
      <small><FileText size={11} /> Governed retrieval ({rows.length})</small>
      <ol className="retrieval-list">
        {rows.map((d, j) => (
          <li key={`${d.title}-${d.namespace}-${d.classification}-${j}`} className="retrieval-item">
            <span className="retrieval-title">
              {d.title}
              {d.isInjectionCanary && <span className="retrieval-canary-badge">canary</span>}
            </span>
            <span className="retrieval-meta">
              <span>{d.namespace} / {d.classification}</span>
              {d.tenant && <span>tenant {d.tenant}</span>}
              {d.score && <span>score {d.score}</span>}
              {d.canaryType && <span>{d.canaryType}</span>}
              {d.reason && <span>{d.reason}</span>}
            </span>
          </li>
        ))}
      </ol>
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
      <button type="button" title="Helpful" className="fb-btn fb-up" onClick={() => submit(1)}><ThumbsUp size={12} /></button>
      <button type="button" title="Not helpful" className="fb-btn fb-down" onClick={() => setState({ ...state, showNote: true, rating: -1 })}><ThumbsDown size={12} /></button>
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
        <span className="isa-pill">{allMet ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}</span>
        <span>Done criteria — <b>{isa.met}/{isa.total}</b> met</span>
        <span className="isa-chev">{open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</span>
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
