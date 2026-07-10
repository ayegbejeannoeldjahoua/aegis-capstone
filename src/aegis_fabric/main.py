from __future__ import annotations

import asyncio
import hashlib
import pathlib
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .audit import last as audit_last
from .audit import trace as audit_trace
from .audit import verify_chain
from .auth import Subject, get_subject, require_admin, validate_token
from . import export_state, rbac
from . import operational_metrics
from .admin import router as admin_router
from .values_docs import router as values_docs_router
from .dashboard_api import router as dashboard_router
from .db import close_pool, init_pool, ping
from .migrate import migrate
from .errors import install_exception_handlers
from .logging_config import configure_logging, get_logger, log_event, request_id_var
from .models import registry
from .policy import decide, require
from .provisioning import bootstrap
from .ratelimit import limiter
from .runtime import runtime_cell
from .settings import settings
from .telemetry import init_telemetry
from .db import run_db
from .values import resolve_values

logger = get_logger("aegis.api")


async def _export_loop():
    """Background daemon: when a governance change is detected (new admin audit event),
    re-export the idempotent state seed to SAF_EXPORT_PATH so the on-disk setup file stays
    current for a bare-scratch reinstall. Debounced by SAF_EXPORT_INTERVAL; never fatal."""
    last_seq = -1
    path = pathlib.Path(settings.export_path)
    while True:
        try:
            seq = await run_db(export_state.latest_admin_seq)
            if seq != last_seq:
                sql = await run_db(export_state.build_seed_sql)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(sql, encoding="utf-8")
                tmp.replace(path)  # atomic swap so readers never see a half-written file
                last_seq = seq
                log_event(logger, 20, "state_exported", path=str(path), admin_seq=seq)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - export must never crash the app
            log_event(logger, 30, "state_export_failed", error=str(e))
        await asyncio.sleep(max(2, settings.export_interval_seconds))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_pool()
    if settings.run_migrations_on_startup:
        try:
            result = migrate()
            log_event(logger, 20, "migrations_applied", applied=result.get("applied", []))
        except Exception as e:  # noqa: BLE001
            log_event(logger, 40, "migration_failed", error=str(e))
    if settings.push_opa_policy_on_startup:
        try:
            rbac.sync_opa_policy()
        except Exception as e:  # noqa: BLE001
            log_event(logger, 30, "opa_policy_push_failed_on_startup", error=str(e))
    if settings.sync_opa_on_startup:
        try:
            rbac.sync_opa()
        except Exception as e:  # noqa: BLE001
            log_event(logger, 30, "opa_sync_failed_on_startup", error=str(e))
    init_telemetry(app)
    log_event(logger, 20, "startup", env=settings.env)
    export_task = asyncio.create_task(_export_loop()) if settings.export_enabled else None
    try:
        yield
    finally:
        if export_task is not None:
            export_task.cancel()
        close_pool()
        log_event(logger, 20, "shutdown")


app = FastAPI(title="Aegis AI Governance Platform", version="1.14.3", lifespan=lifespan)
install_exception_handlers(app)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    try:
        # Coarse rate limiting keyed by bearer-token hash (or client host).
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = "tok:" + hashlib.sha256(auth.encode()).hexdigest()[:16]
        else:
            key = "ip:" + (request.client.host if request.client else "unknown")
        if request.url.path.startswith("/v1/") and not limiter.allow(key):
            return JSONResponse(status_code=429, content={"error": "rate_limited", "request_id": rid})
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(token)


app.include_router(admin_router)
app.include_router(values_docs_router, prefix="/admin")
app.include_router(dashboard_router)


class AskRequest(BaseModel):
    prompt: str
    skill_id: str = "summarise-with-memory"
    model: str | None = None
    conversation_id: str | None = None
    summary_words: int | None = None
    inject_tool_output: bool = False


class ConversationCreate(BaseModel):
    title: str | None = None


class RuntimeExecRequest(BaseModel):
    command: str


# --- Liveness / readiness --------------------------------------------------
@app.get("/health")
def health():
    """Liveness: process is up. No external dependencies checked."""
    return {"ok": True, "service": "aegis-api", "version": app.version}


@app.get("/ready")
async def ready():
    """Readiness: dependencies reachable. Returns 503 if not."""
    checks: dict[str, bool] = {}
    try:
        checks["database"] = await run_db(ping)
    except Exception:
        checks["database"] = False
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"ok": ok, "checks": checks})


# --- Admin surface (shared-secret guarded) ---------------------------------
@app.post("/admin/bootstrap", dependencies=[Depends(require_admin)])
async def admin_bootstrap():
    return await run_db(bootstrap)


@app.get("/v1/scim/v2/Users", dependencies=[Depends(require_admin)])
def scim_users():
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "Resources": []}


# --- Core API --------------------------------------------------------------
@app.post("/v1/ask")
async def ask(req: AskRequest, subject: Subject = Depends(get_subject)):
    from .rbac import role_capabilities
    from .usage import usage

    metrics_token = operational_metrics.begin_chat_turn(subject, req.skill_id)
    mc = 0
    acquired_slot = False
    try:
        caps = await run_db(role_capabilities, subject.tenant_id, subject.role)
        mc = caps.get("max_concurrent_requests", 0)
        if not usage.acquire_slot(subject.tenant_id, subject.sub, mc):
            snapshot = operational_metrics.error_snapshot(429, {"error": "max_concurrent_requests"})
            await run_db(operational_metrics.persist_snapshot, snapshot)
            raise HTTPException(status_code=429, detail={"error": "max_concurrent_requests"})
        acquired_slot = True
        if req.skill_id == "summarise-with-memory":
            from .workflow import summarise_with_memory

            result = await summarise_with_memory(
                subject, req.prompt, req.skill_id, req.model, req.summary_words, req.inject_tool_output
            )
        else:
            from .skill_runner import run_generic_skill

            result = await run_generic_skill(
                subject, req.prompt, req.skill_id, req.model, req.summary_words, req.inject_tool_output
            )
        if isinstance(result, dict):
            operational_metrics.set_trace_id(result.get("trace_id"))
        snapshot = operational_metrics.snapshot(status="success")
        await run_db(operational_metrics.persist_snapshot, snapshot)
        if isinstance(result, dict):
            from . import chat_history

            saved = await run_db(
                chat_history.append_turn,
                subject,
                req.conversation_id,
                req.prompt,
                result,
                snapshot,
                req.model,
            )
            result["conversation_id"] = saved["conversation_id"]
            result["conversation"] = saved["conversation"]
        return result
    except HTTPException as exc:
        snapshot = operational_metrics.error_snapshot(exc.status_code, exc.detail)
        await run_db(operational_metrics.persist_snapshot, snapshot)
        raise
    except Exception as exc:
        snapshot = operational_metrics.exception_snapshot(exc)
        await run_db(operational_metrics.persist_snapshot, snapshot)
        raise
    finally:
        if acquired_slot:
            usage.release_slot(subject.tenant_id, subject.sub, mc)
        try:
            operational_metrics.reset_chat_turn(metrics_token)
        except Exception:
            pass


@app.post("/v1/runtime/exec")
async def runtime_exec(req: RuntimeExecRequest, subject: Subject = Depends(get_subject)):
    """Governed sandbox execution. Requires a lead role and an allow decision
    from the PDP for the runtime.exec action (network default-deny)."""
    values = await run_db(resolve_values, subject.tenant_id, subject.team_id, subject.role, subject.email, None)
    if subject.role != "lead":
        raise HTTPException(status_code=403, detail="runtime.exec requires lead role")
    trace_id = uuid.uuid4().hex
    d = await decide(subject, "runtime.exec",
                     {"tenant_id": subject.tenant_id, "network": values.runtime_network}, values)
    require(d)
    result = await run_db(
        runtime_cell.exec, req.command, subject.tenant_id, trace_id,
        timeout=(values.runtime_max_seconds or None),
        mem_limit=(f"{values.runtime_memory_mb}m" if values.runtime_memory_mb else None),
        network=values.runtime_network,
    )
    return {"trace_id": trace_id, **result.model_dump()}


@app.get("/v1/me")
async def me(subject: Subject = Depends(get_subject)):
    """The caller's identity plus the admin capabilities of their role, so the UI can
    decide which admin surfaces to show and call them with the OIDC bearer."""
    caps = await run_db(rbac.role_capabilities, subject.tenant_id, subject.role)
    return {
        "email": subject.email, "tenant_id": subject.tenant_id, "team_id": subject.team_id, "role": subject.role,
        "admin_scope": caps.get("admin_scope", "none"),
        "can_manage_users": caps.get("can_manage_users", False),
        "can_manage_roles": caps.get("can_manage_roles", False),
        "can_edit_governance": caps.get("can_edit_governance", False),
        "can_register_skills": caps.get("can_register_skills", False),
        "can_delete_tenant": caps.get("can_delete_tenant", False),
        "audit_scope": caps.get("audit_scope", "none"),
    }


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/v1/me/password")
async def change_my_password(req: PasswordChange, subject: Subject = Depends(get_subject)):
    """Self-service password change for the logged-in user. The caller must prove
    knowledge of their *current* password (re-authenticated against Keycloak) before
    a new one is set. Authorization is implicit: a user can only change their own."""
    from . import keycloak_admin
    from .audit import append_event

    if not settings.kc_provisioning_enabled:
        raise HTTPException(status_code=503, detail="self-service password change is disabled")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="new password must be at least 8 characters")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=400, detail="new password must differ from the current one")

    username = subject.token_claims.get("preferred_username") or subject.email
    try:
        ok = keycloak_admin.verify_password(username, req.current_password)
    except Exception as e:  # noqa: BLE001 -- IdP unreachable, etc.
        raise HTTPException(status_code=503, detail=f"identity provider unreachable: {e}")
    if not ok:
        raise HTTPException(status_code=401, detail="current password is incorrect")

    keycloak_admin.set_password(subject.sub, req.new_password)
    try:  # audit the *event*, never the secret material
        append_event(
            trace_id=uuid.uuid4().hex, span_id=None, parent_span_id=None,
            tenant_id=subject.tenant_id, subject=subject.email, action="me.password.change",
            resource=subject.email, policy_version="policy-v1", values_version="self-service",
            decision="allow", reason=None, payload={"self_service": True},
        )
    except Exception as e:  # noqa: BLE001 -- auditing must never break the operation
        log_event(logger, 30, "password_change_audit_failed", error=str(e))
    return {"ok": True}


@app.delete("/v1/memory/{memory_id}")
async def erase_memory(memory_id: str, subject: Subject = Depends(get_subject)):
    """Right-to-erasure: delete a memory, gated by the role's can_erase capability.
    If the role's erase_requires_approval is set, the deletion is queued for dual control."""
    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid memory id")
    values = await run_db(resolve_values, subject.tenant_id, subject.team_id, subject.role, subject.email, None)
    d = await decide(subject, "memory.delete", {"tenant_id": subject.tenant_id, "memory_id": memory_id}, values)
    from .audit import append_event
    try:
        await run_db(append_event, trace_id=uuid.uuid4().hex, span_id=None, parent_span_id=None,
                     tenant_id=subject.tenant_id, subject=subject.email, action="memory.delete", resource=memory_id,
                     policy_version=values.policy_version, values_version=values.values_version,
                     decision=d.decision, reason=";".join(d.reasons), payload={})
    except Exception:  # noqa: BLE001
        pass
    require(d)
    if values.erase_requires_approval:
        from .approvals import create_pending

        return await run_db(create_pending, subject.tenant_id, "memory.erase",
                            {"memory_id": memory_id}, subject.email, "right-to-erasure")
    from .memory import memory_store

    rows = await run_db(memory_store.delete, subject.tenant_id, memory_id)
    return {"ok": True, "deleted": memory_id, "rows": rows}


@app.get("/v1/models")
def models(subject: Subject = Depends(get_subject)):
    return {
        "default_model": registry.default_model_id(),
        "models": registry.catalog(),
        "registry": registry.raw,
    }


@app.get("/v1/chat/conversations")
async def chat_conversations(
    month: str | None = None,
    q: str | None = None,
    limit: int = 50,
    subject: Subject = Depends(get_subject),
):
    from . import chat_history

    rows = await run_db(chat_history.list_conversations, subject, month_key=month, query=q, limit=limit)
    return {"month": month or chat_history.current_month_key(), "conversations": rows}


@app.post("/v1/chat/conversations")
async def chat_conversation_create(req: ConversationCreate, subject: Subject = Depends(get_subject)):
    from . import chat_history

    return await run_db(chat_history.create_conversation, subject, title=req.title)


@app.get("/v1/chat/conversations/{conversation_id}/messages")
async def chat_conversation_messages(
    conversation_id: str,
    month: str | None = None,
    subject: Subject = Depends(get_subject),
):
    from . import chat_history

    messages = await run_db(chat_history.get_messages, subject, conversation_id, month_key=month)
    if messages is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"conversation_id": conversation_id, "month": month, "messages": messages}


@app.delete("/v1/chat/conversations/{conversation_id}")
async def chat_conversation_archive(conversation_id: str, subject: Subject = Depends(get_subject)):
    from . import chat_history

    ok = await run_db(chat_history.archive_conversation, subject, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


@app.get("/v1/skills")
def list_skills(subject: Subject = Depends(get_subject)):
    """Read-only catalog of available skills (any authenticated user)."""
    from .skills import skill_registry

    return {"skills": skill_registry.catalog()}


@app.get("/v1/tools")
def list_tools(subject: Subject = Depends(get_subject)):
    """Read-only catalog of available tools (any authenticated user)."""
    from .tools import catalog as tool_catalog

    return {"tools": tool_catalog()}


# --- Audit (tenant-scoped reads; chain verification is admin-only) ---------
@app.get("/v1/audit/last")
async def audit_last_endpoint(limit: int = 20, month: str | None = None, subject: Subject = Depends(get_subject)):
    from .rbac import role_capabilities

    scope = (await run_db(role_capabilities, subject.tenant_id, subject.role)).get("audit_scope", "own")
    return {"events": await run_db(audit_last, subject.tenant_id, scope, subject.email, limit, month), "month": month}


@app.get("/v1/audit/trace/{trace_id}")
async def audit_trace_endpoint(trace_id: str, subject: Subject = Depends(get_subject)):
    from .rbac import role_capabilities

    scope = (await run_db(role_capabilities, subject.tenant_id, subject.role)).get("audit_scope", "own")
    return {"trace_id": trace_id, "events": await run_db(audit_trace, trace_id, subject.tenant_id, scope, subject.email)}


@app.get("/v1/audit/verify", dependencies=[Depends(require_admin)])
async def audit_verify_endpoint():
    return await run_db(verify_chain)


# --- WebSocket (auth via first message, never the URL) ---------------------
@app.websocket("/v1/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    # Authenticate via the Authorization header or an initial auth frame; the
    # token is deliberately NOT accepted as a query parameter (URLs leak into
    # logs, proxies and browser history).
    token: str | None = None
    auth_header = ws.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    if not token:
        try:
            first = await ws.receive_json()
        except Exception:
            await ws.close(code=4401)
            return
        if first.get("type") != "auth" or not first.get("token"):
            await ws.send_json({"type": "error", "error": "first frame must be {type:'auth', token:...}"})
            await ws.close(code=4401)
            return
        token = first["token"]
    try:
        subject = await validate_token(token)
    except Exception as e:
        await ws.send_json({"type": "error", "error": str(e)})
        await ws.close(code=4401)
        return

    await ws.send_json({"type": "ready", "tenant_id": subject.tenant_id, "role": subject.role, "email": subject.email})
    from .workflow import summarise_with_memory

    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
                continue
            if msg.get("type") != "ask":
                await ws.send_json({"type": "error", "error": "expected type=ask"})
                continue
            try:
                result = await summarise_with_memory(
                    subject, msg.get("prompt", ""), msg.get("skill_id", "summarise-with-memory"),
                    msg.get("model"), msg.get("summary_words"), bool(msg.get("inject_tool_output", False)),
                )
                await ws.send_json({"type": "answer", "data": result})
            except HTTPException as e:
                await ws.send_json({"type": "error", "error": e.detail})
    except WebSocketDisconnect:
        return
