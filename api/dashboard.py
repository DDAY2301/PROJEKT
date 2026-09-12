"""Customer dashboard endpoints for Project Visibility.

The dashboard is intentionally read-oriented: it aggregates project, payment,
publication, visual-QA and revision state in one response. It also provides a
secure source ZIP download through the backend so customers do not need direct
GitHub credentials.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import api.billing as billing
import api.main as core


class DomainIn(BaseModel):
    domain: str = Field(default="", max_length=253)


def ensure_dashboard_schema() -> None:
    billing.ensure_billing_schema()
    with core.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_domains (
              project_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              domain TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'not_connected',
              updated_at TEXT NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id),
              FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS revisions (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              instruction TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            """
        )


def _audit(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _public_url(project: dict[str, Any], audit: dict[str, Any]) -> str | None:
    if audit.get("public_url"):
        return str(audit["public_url"])
    repo = project.get("repo_name")
    if repo:
        return f"https://{core.GITHUB_OWNER.lower()}.github.io/{repo}/"
    return None


def _domain(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"^https?://", "", value).strip("/")
    if not value:
        return ""
    if len(value) > 253 or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", value):
        raise HTTPException(422, "Enter a valid domain such as www.example.com")
    return value


@core.app.get("/dashboard/projects")
async def dashboard_projects(user_id: str = Depends(core.current_user)):
    ensure_dashboard_schema()
    with core.db() as con:
        rows = con.execute(
            "SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
            (user_id,),
        ).fetchall()
        result = []
        for row in rows:
            project = dict(row)
            audit = _audit(project.get("last_audit_json"))
            payment = con.execute(
                "SELECT status,amount_total,currency,stripe_session_id,updated_at FROM payments WHERE project_id=? AND user_id=?",
                (project["id"], user_id),
            ).fetchone()
            domain = con.execute(
                "SELECT domain,status,updated_at FROM project_domains WHERE project_id=? AND user_id=?",
                (project["id"], user_id),
            ).fetchone()
            revision_count = con.execute(
                "SELECT COUNT(*) AS n FROM revisions WHERE project_id=?",
                (project["id"],),
            ).fetchone()["n"]
            config = json.loads(project.get("config_json") or "{}")
            issues = audit.get("issues") or []
            severe = sum(1 for item in issues if isinstance(item, dict) and item.get("severity") in {"critical", "high"})
            result.append({
                "id": project["id"],
                "name": project["name"],
                "package": project["package"],
                "status": project["status"],
                "repo_name": project.get("repo_name"),
                "organization": config.get("organization") or "",
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
                "auto_fix_attempts": int(project.get("auto_fix_attempts") or 0),
                "public_url": _public_url(project, audit),
                "public_live": bool(audit.get("public_live")),
                "payment": dict(payment) if payment else None,
                "domain": dict(domain) if domain else {"domain": "", "status": "not_connected", "updated_at": None},
                "revision_count": int(revision_count or 0),
                "visual_qa": audit.get("visual_qa") or None,
                "issue_count": len(issues),
                "severe_issue_count": severe,
            })
    return result


@core.app.put("/projects/{project_id}/domain")
async def save_project_domain(project_id: str, data: DomainIn, user_id: str = Depends(core.current_user)):
    ensure_dashboard_schema()
    domain = _domain(data.domain)
    with core.db() as con:
        project = con.execute(
            "SELECT id FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        status = "saved" if domain else "not_connected"
        con.execute(
            """
            INSERT INTO project_domains(project_id,user_id,domain,status,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
              domain=excluded.domain,status=excluded.status,updated_at=excluded.updated_at
            """,
            (project_id, user_id, domain, status, core.now_iso()),
        )
    return {
        "project_id": project_id,
        "domain": domain,
        "status": status,
        "note": "Domain is saved in the project workspace. DNS/Pages verification is a separate deployment step.",
    }


@core.app.get("/projects/{project_id}/source.zip")
async def download_project_source(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        project = con.execute(
            "SELECT id,repo_name,name FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    if not project["repo_name"]:
        raise HTTPException(409, "Project source is not published yet")
    url = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{project['repo_name']}/zipball/main"
    async with httpx.AsyncClient(timeout=120, headers=core.github_headers(), follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise HTTPException(502, "Could not download the generated source from GitHub")
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", project["name"]).strip("-") or "website"
    return Response(
        content=response.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}-source.zip"'},
    )


@core.app.get("/projects/{project_id}/visual-qa")
async def project_visual_qa(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        row = con.execute(
            "SELECT last_audit_json FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    audit = _audit(row["last_audit_json"])
    return {
        "project_id": project_id,
        "visual_qa": audit.get("visual_qa"),
        "issues": [item for item in (audit.get("issues") or []) if str(item.get("code") or "").startswith("VISUAL_")],
    }
