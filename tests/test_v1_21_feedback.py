"""v1.21 PAI slice 3 -- regression guards for the feedback + thinking-skill +
Chat thumbs widget additions."""
import base64
import json
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import aegis_fabric.feedback as feedback_mod

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Migration 0008 + feedback module shape
# ---------------------------------------------------------------------------

def test_migration_0008_creates_turn_feedback_with_rls():
    sql = (ROOT / "deploy" / "postgres" / "migrations" / "0008_feedback.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS turn_feedback" in sql
    assert "CHECK (rating IN (-1, 1))" in sql
    assert "trace_id     TEXT NOT NULL" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE  ROW LEVEL SECURITY" in sql
    assert "tenant_isolation_turn_feedback" in sql


def test_feedback_record_rejects_invalid_rating():
    bad = feedback_mod.Feedback(trace_id="t1", rating=2)  # not -1 or +1
    import pytest
    with pytest.raises(ValueError):
        feedback_mod.record("acme-corp", "u@x", bad)


def test_feedback_module_exports():
    """Public surface must include record, list_low_rated, skill_summary."""
    for name in ("record", "list_low_rated", "skill_summary", "Feedback"):
        assert hasattr(feedback_mod, name), f"feedback.{name} missing"


# ---------------------------------------------------------------------------
# Thinking skills: 3 signed manifests
# ---------------------------------------------------------------------------

def _verify_manifest_sig(m: dict) -> bool:
    """Replay the verifier: drop signature, canonicalise, check Ed25519."""
    sig = m["signature"]["value"]
    pub_b64 = "Ms5VAI+2S9EJZZSGcV/EPwAyvpx/RGbRELjcIrfgGc8="  # fixture demo pub key
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    body = {k: v for k, v in m.items() if k != "signature"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    try:
        pub.verify(base64.b64decode(sig), canon)
        return True
    except Exception:
        return False


def test_three_thinking_skills_present_and_signed():
    for sid in ("council", "redteam", "firstprinciples"):
        p = ROOT / "configs" / "skills" / f"{sid}.skill.yaml"
        assert p.is_file(), f"{p} missing"
        m = yaml.safe_load(p.read_text())
        assert m["skill_id"] == sid
        assert m["entrypoint"] == "aegis_fabric.skill_runner:run_generic_skill"
        assert m["risk_tier"].startswith("T1")
        # Each must carry a prompt_preamble that steers the model.
        assert "prompt_preamble" in m and len(m["prompt_preamble"]) > 40
        assert _verify_manifest_sig(m), f"{sid} signature invalid"


# ---------------------------------------------------------------------------
# Admin endpoints wired into the router
# ---------------------------------------------------------------------------

def test_admin_endpoints_registered():
    """The three turn-feedback endpoints must be on the admin router."""
    from aegis_fabric.admin import router
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/admin/turn-feedback" in paths
    assert "/admin/turn-feedback/low" in paths
    assert "/admin/turn-feedback/skills" in paths


# ---------------------------------------------------------------------------
# Frontend Chat thumbs widget
# ---------------------------------------------------------------------------

def test_chat_jsx_renders_thumbs_for_assistant_turns():
    txt = (ROOT / "frontend" / "src" / "pages" / "Chat.jsx").read_text()
    # Defines a Thumbs component
    assert "function Thumbs(" in txt
    # POSTs to the new endpoint with rating + trace_id
    assert "/admin/turn-feedback" in txt
    assert "trace_id" in txt and "rating" in txt
    # Renders <Thumbs/> on assistant bubbles
    assert "<Thumbs trace_id={m.trace_id}" in txt
    # Captures trace_id + skill_id when receiving the response
    assert "trace_id: r.trace_id" in txt
    assert "skill_id: r.skill_id" in txt
