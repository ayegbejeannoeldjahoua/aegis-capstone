import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
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
} from "lucide-react";
import { api } from "../api/client.js";
import {
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

function currentMonthKey() {
  return new Date().toISOString().slice(0, 7);
}

function modelCatalog(payload) {
  if (Array.isArray(payload?.models)) return payload.models;
  const providers = payload?.registry?.providers || payload?.providers || {};
  return Object.entries(providers).flatMap(([provider, config]) =>
    (config?.models || []).map((model) => ({
      model_id: model.id,
      provider,
      type: config.type,
      region: config.region,
      local: Boolean(config.local),
    })),
  );
}

function messageFromApi(message) {
  return {
    id: message.message_id,
    role: message.role,
    text: message.content || "",
  };
}

function conversationTime(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export default function Chat({ profile, claims = {}, onHome, onLogout, go }) {
  const [prompt, setPrompt] = useState("");
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [conversationQuery, setConversationQuery] = useState("");
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [conversationErr, setConversationErr] = useState("");
  const endRef = useRef(null);
  const navItems = assistantNavItems(profile || {});
  const month = currentMonthKey();

  const selectedModelLabel = useMemo(() => {
    const model = models.find((item) => item.model_id === selectedModel);
    if (!model) return "Default model";
    return `${model.provider} · ${model.model_id}`;
  }, [models, selectedModel]);

  const loadConversations = useCallback(async (query = "") => {
    setConversationErr("");
    try {
      const qs = new URLSearchParams({ month, limit: "50" });
      if (query.trim()) qs.set("q", query.trim());
      const data = await api(`/v1/chat/conversations?${qs.toString()}`);
      setConversations(data.conversations || []);
    } catch (e) {
      setConversationErr(String(e.message || e));
    }
  }, [month]);

  useEffect(() => {
    if (endRef.current) endRef.current.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  useEffect(() => {
    loadConversations("");
  }, [loadConversations]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadConversations(conversationQuery);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [conversationQuery, loadConversations]);

  useEffect(() => {
    let mounted = true;
    api("/v1/models")
      .then((data) => {
        if (!mounted) return;
        const catalog = modelCatalog(data);
        setModels(catalog);
        const defaultModel = data.default_model || catalog[0]?.model_id || "";
        setSelectedModel((current) => current || defaultModel);
      })
      .catch(() => {
        if (mounted) setModels([]);
      });
    return () => { mounted = false; };
  }, []);

  async function send(e) {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || busy) return;
    setLog((items) => [...items, { role: "user", text }]);
    setPrompt("");
    setBusy(true);
    try {
      const body = {
        prompt: text,
        skill_id: "assistant",
        conversation_id: activeConversationId,
        model: selectedModel || null,
      };
      const response = await api("/v1/ask", { method: "POST", body });
      if (response.conversation_id) setActiveConversationId(response.conversation_id);
      setLog((items) => [...items, { role: "assistant", text: response.answer || "(no answer returned)" }]);
      loadConversations(conversationQuery);
    } catch (e) {
      setLog((items) => [...items, { role: "error", text: `Could not complete: ${String(e.message || e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function openConversation(id) {
    if (!id) return;
    setConversationErr("");
    try {
      const qs = new URLSearchParams({ month });
      const data = await api(`/v1/chat/conversations/${id}/messages?${qs.toString()}`);
      setActiveConversationId(id);
      setLog((data.messages || []).map(messageFromApi));
    } catch (e) {
      setConversationErr(String(e.message || e));
    }
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
    setActiveConversationId(null);
  }

  return (
    <div className="chat aegis-chat">
      <ShellTopBar onBack={onHome} profile={profile} claims={claims} onLogout={onLogout} section="Chat / AI Assistant" />
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
          </div>
          <label className="aegis-chat-search">
            <Search size={13} />
            <input
              type="search"
              placeholder="Search conversations"
              aria-label="Search conversations"
              value={conversationQuery}
              onChange={(event) => setConversationQuery(event.target.value)}
            />
          </label>
          {conversationErr && <div className="aegis-chat-conversation-error">{conversationErr}</div>}
          <div className="aegis-chat-conversation-list">
            {conversations.map((conversation) => {
              const active = conversation.conversation_id === activeConversationId;
              return (
                <button
                  key={conversation.conversation_id}
                  type="button"
                  className={cx("aegis-chat-conversation-item", active && "active")}
                  onClick={() => openConversation(conversation.conversation_id)}
                >
                  <span>{conversation.title}</span>
                  <small>{conversationTime(conversation.last_message_at || conversation.updated_at)}</small>
                </button>
              );
            })}
            {conversations.length === 0 && (
              <div className="aegis-chat-conversation-empty">
                <MessageSquare size={16} />
                <span>No saved conversations yet</span>
              </div>
            )}
          </div>
        </aside>

        <main className="aegis-chat-main">
          <div className="aegis-chat-main-head">
            <div>
              <h1>AI Assistant (Chat)</h1>
              <p>{profile?.role || "role pending"} · {profile?.tenant_id || "tenant pending"}</p>
            </div>
            <div className="aegis-chat-main-tools">
              <label className="aegis-chat-model-select" title={selectedModelLabel}>
                <Sparkles size={13} />
                <select
                  value={selectedModel}
                  onChange={(event) => setSelectedModel(event.target.value)}
                  aria-label="Model"
                >
                  {models.map((model) => (
                    <option key={model.model_id} value={model.model_id}>
                      {model.provider} · {model.model_id}
                    </option>
                  ))}
                  {models.length === 0 && <option value="">Default model</option>}
                </select>
              </label>
              <AegisButton type="button" variant="ghost" icon={Plus} onClick={newChat}>New chat</AegisButton>
            </div>
          </div>

          <section className="chat-log aegis-chat-log" aria-live="polite">
            {log.length === 0 && (
              <EmptyPanel icon={MessageSquare} title="Start a conversation">
                Ask Aegis a question and return to it later from your saved conversations.
              </EmptyPanel>
            )}
            {log.map((message, index) => (
              <div key={message.id || index} className={cx("aegis-bubble-row", message.role === "user" && "from-user", message.role === "error" && "from-error")}>
                {message.role !== "user" && (
                  <div className={cx("aegis-bubble-avatar", message.role === "error" && "error")}>
                    {message.role === "error" ? <AlertTriangle size={13} /> : <Sparkles size={13} />}
                  </div>
                )}
                <article className={`bubble aegis-bubble ${message.role}`}>
                  <div className="bubble-body">{message.text}</div>
                </article>
              </div>
            ))}
            <div ref={endRef} />
          </section>

          <form className="chat-input aegis-chat-input" onSubmit={send}>
            <div className="aegis-composer">
              <Paperclip size={14} />
              <input value={prompt} placeholder="Ask Aegis..." onChange={(event) => setPrompt(event.target.value)} />
              <AegisButton type="submit" disabled={busy} icon={Send}>
                {busy ? "Sending" : "Send"}
              </AegisButton>
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}
