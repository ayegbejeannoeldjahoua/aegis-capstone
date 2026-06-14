"""Values documents — human-authored prose statements of values at each scope.

Scopes (top → bottom):
  organization   — single org-wide statement; written by platform-admin
  department     — per-tenant; written by tenant-admin OR platform-admin of that tenant
  team           — per-team within a tenant; written by tenant-admin OR platform-admin
  role           — per-role within a tenant; written by tenant-admin OR platform-admin
  individual     — per-user (scope_id = user email); written by that user only

Access matrix (writes):
  platform-admin: organization + (department/team/role/individual within own tenant)
  tenant-admin  : department/team/role/individual within own tenant
  individual    : own individual doc only

Reads: anyone authenticated can read organization + their own tenant's docs at every
level they belong to.
"""
from __future__ import annotations
import io
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel, Field

from .auth import Subject, AdminPrincipal, get_subject, admin_principal, admin_principal_optional
from .db import get_conn, run_db

router = APIRouter(prefix="/values", tags=["values"])


# ============================================================
# File-text extraction for the "Load from file" button on Values
# ============================================================
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024   # 2 MB cap; values docs should be short


def _extract_docx(data: bytes) -> str:
    from docx import Document as _DocxDocument
    doc = _DocxDocument(io.BytesIO(data))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    rdr = PdfReader(io.BytesIO(data))
    out = []
    for page in rdr.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t:
            out.append(t)
    return "\n\n".join(out)


@router.post("/extract")
async def extract_text_from_upload(
    file: UploadFile = File(...),
    subject: Subject = Depends(get_subject),
):
    """Extract text from an uploaded values document.

    Returns the suggested title (from filename) and body markdown so the
    Values UI can pre-fill the editor. Authorization to actually save the
    document is enforced by POST /values/documents (same access matrix);
    this endpoint just helps the user compose the body. Accepts
    .txt / .md / .docx / .pdf, hard-capped at 2 MB so huge files don't
    drift into the system prompt later."""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"file too large; cap is {_MAX_UPLOAD_BYTES // 1024} KB")
    name = (file.filename or "uploaded").rsplit("/", 1)[-1]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    try:
        if ext in (".txt", ".md", ".markdown"):
            text = raw.decode("utf-8", errors="replace")
        elif ext == ".docx":
            text = _extract_docx(raw)
        elif ext == ".pdf":
            text = _extract_pdf(raw)
        else:
            raise HTTPException(415, f"unsupported file type {ext or '(unknown)'}; "
                                     f"accepts .txt .md .docx .pdf")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not extract text: {e}")
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "no extractable text in file")
    # Suggested title from the filename, minus extension
    suggested_title = name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip() or "Untitled"
    return {
        "filename":        name,
        "size_bytes":      len(raw),
        "suggested_title": suggested_title,
        "body_md":         text,
    }

VALID_SCOPES = {"organization", "department", "team", "role", "individual"}


class ValuesDocIn(BaseModel):
    scope_type: str = Field(..., description="one of: organization, department, team, role, individual")
    tenant_id:  str | None = None
    scope_id:   str | None = None
    title:      str
    body_md:    str


class ValuesDocOut(BaseModel):
    id:           str
    scope_type:   str
    tenant_id:    str | None
    scope_id:     str | None
    title:        str
    body_md:      str
    author_user:  str
    created_at:   str
    updated_at:   str


# ============================================================
# Access helpers
# ============================================================
def _is_platform_admin(principal: AdminPrincipal | None) -> bool:
    return bool(principal) and principal.scope == "platform"


def _is_tenant_admin(principal: AdminPrincipal | None) -> bool:
    return bool(principal) and principal.scope == "tenant"


def _can_write(principal: AdminPrincipal, subject: Subject,
               scope_type: str, tenant_id: str | None, scope_id: str | None) -> bool:
    if scope_type == "organization":
        return _is_platform_admin(principal)
    if scope_type == "individual":
        # Any authenticated user can edit their own; admins can also edit anyone's in their tenant.
        if subject and scope_id == subject.email:
            return True
        if _is_platform_admin(principal):
            return True
        if _is_tenant_admin(principal) and principal.tenant_id == tenant_id:
            return True
        return False
    # department / team / role
    if scope_type in ("department", "team", "role"):
        if _is_platform_admin(principal) and principal.tenant_id == tenant_id:
            return True
        if _is_tenant_admin(principal) and principal.tenant_id == tenant_id:
            return True
        return False
    return False


def _can_read(subject: Subject, scope_type: str, tenant_id: str | None, scope_id: str | None) -> bool:
    if scope_type == "organization":
        return True
    if scope_type == "individual":
        # User reads their own; admins read in their tenant
        if scope_id == subject.email:
            return True
        if subject.role in ("platform-admin", "tenant-admin") and subject.tenant_id == tenant_id:
            return True
        return False
    # department / team / role — readable to anyone in that tenant
    if scope_type in ("department", "team", "role"):
        return subject.tenant_id == tenant_id
    return False


# ============================================================
# Endpoints
# ============================================================
def _row_to_out(r: dict) -> dict:
    return {
        "id":          r["id"],
        "scope_type":  r["scope_type"],
        "tenant_id":   r["tenant_id"],
        "scope_id":    r["scope_id"],
        "title":       r["title"],
        "body_md":     r["body_md"],
        "author_user": r["author_user"],
        "created_at":  str(r["created_at"]),
        "updated_at":  str(r["updated_at"]),
    }


@router.get("/documents")
async def list_documents(
    scope_type: str | None = None,
    tenant_id:  str | None = None,
    scope_id:   str | None = None,
    subject: Subject = Depends(get_subject),
):
    """List values documents visible to the caller. Filter by any of scope_type/tenant_id/scope_id."""
    if scope_type and scope_type not in VALID_SCOPES:
        raise HTTPException(400, f"scope_type must be one of {sorted(VALID_SCOPES)}")

    def _q():
        wheres, params = [], []
        if scope_type:
            wheres.append("scope_type=%s"); params.append(scope_type)
        if tenant_id:
            wheres.append("tenant_id=%s"); params.append(tenant_id)
        if scope_id:
            wheres.append("scope_id=%s"); params.append(scope_id)
        sql = ("SELECT id::text, scope_type, tenant_id, scope_id, title, body_md, author_user, "
               "created_at, updated_at FROM values_documents")
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY scope_type, tenant_id NULLS FIRST, scope_id NULLS FIRST"
        with get_conn() as conn:
            return list(conn.execute(sql, params).fetchall())

    rows = await run_db(_q)
    visible = [r for r in rows if _can_read(subject, r["scope_type"], r["tenant_id"], r["scope_id"])]
    return [_row_to_out(r) for r in visible]


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, subject: Subject = Depends(get_subject)):
    def _q():
        with get_conn() as conn:
            return conn.execute(
                "SELECT id::text, scope_type, tenant_id, scope_id, title, body_md, author_user, "
                "created_at, updated_at FROM values_documents WHERE id=%s::uuid",
                (doc_id,),
            ).fetchone()
    r = await run_db(_q)
    if not r:
        raise HTTPException(404, "not found")
    if not _can_read(subject, r["scope_type"], r["tenant_id"], r["scope_id"]):
        raise HTTPException(403, "not allowed")
    return _row_to_out(r)


@router.post("/documents", status_code=201)
async def create_document(
    body: ValuesDocIn,
    subject: Subject = Depends(get_subject),
    principal: AdminPrincipal | None = Depends(admin_principal_optional),
):
    if body.scope_type not in VALID_SCOPES:
        raise HTTPException(400, f"scope_type must be one of {sorted(VALID_SCOPES)}")
    if not _can_write(principal, subject, body.scope_type, body.tenant_id, body.scope_id):
        raise HTTPException(403, "not allowed to write at this scope")

    def _q():
        with get_conn() as conn:
            row = conn.execute(
                "INSERT INTO values_documents(scope_type, tenant_id, scope_id, title, body_md, author_user) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (COALESCE(tenant_id,''), scope_type, COALESCE(scope_id,'')) "
                "DO UPDATE SET title=EXCLUDED.title, body_md=EXCLUDED.body_md, "
                "             author_user=EXCLUDED.author_user, updated_at=now() "
                "RETURNING id::text, scope_type, tenant_id, scope_id, title, body_md, author_user, "
                "         created_at, updated_at",
                (body.scope_type, body.tenant_id, body.scope_id,
                 body.title, body.body_md, subject.email),
            ).fetchone()
            return row
    r = await run_db(_q)
    return _row_to_out(r)


@router.put("/documents/{doc_id}")
async def update_document(
    doc_id: str,
    body: ValuesDocIn,
    subject: Subject = Depends(get_subject),
    principal: AdminPrincipal | None = Depends(admin_principal_optional),
):
    def _read():
        with get_conn() as conn:
            return conn.execute(
                "SELECT scope_type, tenant_id, scope_id FROM values_documents WHERE id=%s::uuid",
                (doc_id,),
            ).fetchone()
    existing = await run_db(_read)
    if not existing:
        raise HTTPException(404, "not found")
    if not _can_write(principal, subject, existing["scope_type"],
                      existing["tenant_id"], existing["scope_id"]):
        raise HTTPException(403, "not allowed to edit this document")

    def _q():
        with get_conn() as conn:
            return conn.execute(
                "UPDATE values_documents SET title=%s, body_md=%s, author_user=%s, updated_at=now() "
                "WHERE id=%s::uuid RETURNING id::text, scope_type, tenant_id, scope_id, title, "
                "body_md, author_user, created_at, updated_at",
                (body.title, body.body_md, subject.email, doc_id),
            ).fetchone()
    r = await run_db(_q)
    return _row_to_out(r)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    subject: Subject = Depends(get_subject),
    principal: AdminPrincipal | None = Depends(admin_principal_optional),
):
    def _read():
        with get_conn() as conn:
            return conn.execute(
                "SELECT scope_type, tenant_id, scope_id FROM values_documents WHERE id=%s::uuid",
                (doc_id,),
            ).fetchone()
    existing = await run_db(_read)
    if not existing:
        raise HTTPException(404, "not found")
    if not _can_write(principal, subject, existing["scope_type"],
                      existing["tenant_id"], existing["scope_id"]):
        raise HTTPException(403, "not allowed to delete this document")

    def _q():
        with get_conn() as conn:
            conn.execute("DELETE FROM values_documents WHERE id=%s::uuid", (doc_id,))
    await run_db(_q)
    return None


# ============================================================
# Helper for the frontend: which scopes can THIS user write at?
# ============================================================


@router.get("/scopes")
async def list_writable_scopes(
    subject: Subject = Depends(get_subject),
    principal: AdminPrincipal | None = Depends(admin_principal_optional),
):
    """Returns a structured response telling the UI which scopes to show as editable."""
    out: dict[str, Any] = {
        "user_email":     subject.email,
        "user_tenant_id": subject.tenant_id,
        "user_role":      subject.role,
        "writable": {
            "organization": _is_platform_admin(principal),
            "department":   bool(principal and principal.scope in ("platform", "tenant")
                                 and principal.tenant_id == subject.tenant_id),
            "team":         bool(principal and principal.scope in ("platform", "tenant")
                                 and principal.tenant_id == subject.tenant_id),
            "role":         bool(principal and principal.scope in ("platform", "tenant")
                                 and principal.tenant_id == subject.tenant_id),
            "individual":   True,
        },
    }
    return out


def compose_values_cascade(tenant_id, team_id, role_id, user_email):
    """Return a markdown summary of every values document that applies to the user,
    ordered from broadest (organization) to narrowest (individual). Used by the chat
    to fold the cascade into the model's system prompt."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT scope_type, title, body_md FROM values_documents "
            "WHERE (scope_type='organization') "
            "   OR (scope_type='department' AND tenant_id=%s) "
            "   OR (scope_type='team'       AND tenant_id=%s AND scope_id=%s) "
            "   OR (scope_type='role'       AND tenant_id=%s AND scope_id=%s) "
            "   OR (scope_type='individual' AND tenant_id=%s AND scope_id=%s) "
            "ORDER BY CASE scope_type "
            "  WHEN 'organization' THEN 1 WHEN 'department' THEN 2 "
            "  WHEN 'team' THEN 3 WHEN 'role' THEN 4 WHEN 'individual' THEN 5 END",
            (tenant_id, tenant_id, team_id, tenant_id, role_id, tenant_id, user_email),
        ).fetchall()
    if not rows:
        return ""
    parts = ["VALUES CASCADE that applies to this user (most-restrictive wins; "
             "individual narrows role narrows team narrows department narrows organization):"]
    for r in rows:
        st = r["scope_type"]
        parts.append("### [" + st.upper() + "] " + (r["title"] or ""))
        body = (r["body_md"] or "").strip()
        if len(body) > 1200:
            body = body[:1200] + " ...(truncated)"
        parts.append(body)
    return (chr(10) + chr(10)).join(parts)
