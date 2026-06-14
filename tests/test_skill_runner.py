"""The generic governed runner issues a PDP decision for every action a manifest
declares, caps tool fan-out, and stamps the model purpose + output-token ceiling."""
import asyncio

import aegis_fabric.isa as _sisa
import aegis_fabric.skill_runner as sr
from aegis_fabric.auth import Subject
from aegis_fabric.policy import PolicyDecision
from aegis_fabric.values import ResolvedValues


class _Profile:
    model_id = "ollama/llama3.1:8b"
    provider = "ollama"
    region = "AC1"


class _Result:
    model = "ollama/llama3.1:8b"
    provider = "ollama"
    content = "ok"
    usage = {}


def _setup(monkeypatch, manifest, max_tools=8):
    calls = []

    async def fake_decide(subject, action, resource, values):
        calls.append((action, resource))
        return PolicyDecision(allow=True, reasons=[], decision="allow")

    async def fake_run_db(fn, *a, **k):
        return fn(*a, **k)

    vals = ResolvedValues(tenant_id="acme-corp", team_id="research", role="analyst", user="jane@x",
                          max_tool_calls_per_request=max_tools, max_output_tokens=2048)

    monkeypatch.setattr(sr, "decide", fake_decide)
    monkeypatch.setattr(sr, "run_db", fake_run_db)
    monkeypatch.setattr(_sisa, "save_isa", lambda isa: None)
    monkeypatch.setattr(sr.skill_registry, "verify", lambda sid: manifest)
    monkeypatch.setattr(sr, "resolve_values", lambda *a, **k: vals)
    monkeypatch.setattr(sr.memory_store, "read", lambda *a, **k: [])
    monkeypatch.setattr(sr.memory_store, "write", lambda *a, **k: "mem-1")
    monkeypatch.setattr(sr, "append_event", lambda **k: "h")
    monkeypatch.setattr(sr.registry, "route", lambda *a, **k: [_Profile()])

    async def fake_chat(candidates, messages, temperature=0.2):
        return _Result()
    monkeypatch.setattr(sr.client, "chat_with_fallbacks", fake_chat)
    return calls


_SUBJ = Subject(sub="s", email="jane@acme-corp.example", tenant_id="acme-corp",
                team_id="research", role="analyst", token_claims={})

_MANIFEST = {
    "skill_id": "qa-over-docs", "name": "Q&A",
    "capabilities": {"memory": {"read": [{"namespace": "analyst-notes"}], "write": []},
                     "tools": ["kb_search", "vector_recall", "calculator"],
                     "model": {"outbound": True, "purposes": ["chat"]}},
}


def test_runner_governs_every_action(monkeypatch):
    calls = _setup(monkeypatch, _MANIFEST, max_tools=8)
    out = asyncio.run(sr.run_generic_skill(_SUBJ, "hello", "qa-over-docs"))
    actions = [a for a, _ in calls]
    assert actions[0] == "skill.invoke"
    assert "memory.read" in actions and actions.count("tool.call") == 3 and "model.call" in actions
    # model.call resource carries the manifest purpose + the role's output-token ceiling
    model_res = next(r for a, r in calls if a == "model.call")
    assert model_res["purpose"] == "chat" and model_res["max_output_tokens"] == 2048
    assert out["skill_id"] == "qa-over-docs" and out["tools_used"] == ["kb_search", "vector_recall", "calculator"]


def test_runner_caps_tool_fanout(monkeypatch):
    calls = _setup(monkeypatch, _MANIFEST, max_tools=1)  # cap below declared tool count
    asyncio.run(sr.run_generic_skill(_SUBJ, "hi", "qa-over-docs"))
    assert [a for a, _ in calls].count("tool.call") == 1


def test_runner_stamps_tool_egress(monkeypatch):
    manifest = {**_MANIFEST, "capabilities": {**_MANIFEST["capabilities"], "tools": ["web_fetch"]}}
    calls = _setup(monkeypatch, manifest)
    asyncio.run(sr.run_generic_skill(_SUBJ, "hi", "qa-over-docs"))
    tool_res = next(r for a, r in calls if a == "tool.call")
    assert tool_res["tool_id"] == "web_fetch" and "egress_domain" in tool_res


def test_assistant_system_prompt_allows_general_knowledge():
    """v1.14.1: the chat system prompt must let the model answer general-knowledge questions
    from its own knowledge (not refuse just because the answer isn't in the retrieved docs),
    while still blocking instructions embedded in document/tool content."""
    p = sr.ASSISTANT_SYSTEM_PROMPT.lower()
    assert "general knowledge" in p
    assert "never refuse" in p
    assert "supplementary" in p
    assert "embedded" in p  # prompt-injection guard retained
