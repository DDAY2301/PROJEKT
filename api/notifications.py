"""Transactional customer handoff emails and deployment guidance.

Email delivery is optional and uses Resend when RESEND_API_KEY is configured.
The build never fails because email delivery failed. Every customer can also
retrieve the same deployment guidance from the authenticated dashboard.
"""

from __future__ import annotations

import html
import json
import os
from typing import Any

import httpx
from fastapi import Depends, HTTPException

import api.main as core

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.getenv(
    "RESEND_FROM_EMAIL",
    "Project Visibility <onboarding@resend.dev>",
).strip()
DASHBOARD_URL = os.getenv(
    "PUBLIC_DASHBOARD_URL",
    "https://dday2301.github.io/PROJEKT/dashboard.html",
).strip()


def ensure_notification_schema() -> None:
    with core.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              recipient TEXT NOT NULL,
              provider TEXT NOT NULL DEFAULT 'resend',
              status TEXT NOT NULL,
              provider_id TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(project_id,kind,recipient)
            );
            """
        )


def _audit(value: str | None) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _project_context(project_id: str) -> dict[str, Any] | None:
    with core.db() as con:
        row = con.execute(
            """
            SELECT p.*,u.email AS account_email
            FROM projects p JOIN users u ON u.id=p.user_id
            WHERE p.id=?
            """,
            (project_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["config"] = json.loads(item.get("config_json") or "{}")
    except Exception:
        item["config"] = {}
    item["audit"] = _audit(item.get("last_audit_json"))
    return item


def deployment_guide(project_id: str) -> str:
    project = _project_context(project_id)
    if not project:
        return ""
    config = project["config"]
    repo = project.get("repo_name") or "generated-site"
    public_url = project["audit"].get("public_url") or ""
    name = project.get("name") or "Website"
    return f"""# {name} — source and deployment guide

This website was generated and quality-checked by Project Visibility.

## What is included
- complete static HTML/CSS/JS source
- responsive project images and logo assets
- SEO metadata, robots.txt and sitemap.xml where generated
- source that does not require a build step

## Deploy to your own GitHub account
1. Sign in to GitHub and create a new repository for this website.
2. Download the source ZIP from Project Visibility → Moji projekti → Predaja in koda.
3. Extract the ZIP and place the website files at the root of your new repository.
4. Commit and push the files to the `main` branch.
5. In GitHub open Settings → Pages.
6. Under Build and deployment choose `Deploy from a branch`.
7. Select branch `main` and folder `/ (root)`, then Save.
8. GitHub will display the final public URL after the first deployment finishes.

### Command-line alternative
```bash
git init
git add .
git commit -m "Deploy {name}"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Then enable GitHub Pages from `main / (root)` in repository Settings → Pages.

## Custom domain
After GitHub Pages is working, add your domain in Settings → Pages → Custom domain and create the DNS records requested by GitHub. Do not remove the GitHub Pages DNS records until GitHub shows the domain as verified.

## Current Project Visibility delivery
- Package: {project.get('package') or ''}
- Internal delivery repository: {core.GITHUB_OWNER}/{repo}
- Public URL: {public_url or 'not published yet'}
- Dashboard: {DASHBOARD_URL}

## Generation brief
- Organisation: {config.get('organization') or ''}
- Goal: {config.get('goal') or ''}
- Audience: {config.get('audience') or ''}
- Tone: {config.get('tone') or ''}

Keep this file with the project source as the deployment handoff record.
"""


def _recipient(project: dict[str, Any]) -> str:
    config = project.get("config") or {}
    contact = str(config.get("contact_email") or "").strip().lower()
    return contact or str(project.get("account_email") or "").strip().lower()


def _message(project: dict[str, Any], kind: str) -> tuple[str, str, str]:
    name = str(project.get("name") or "Your website")
    repo = str(project.get("repo_name") or "")
    audit = project.get("audit") or {}
    public_url = str(audit.get("public_url") or "")
    qa = audit.get("visual_qa") or {}
    qa_score = qa.get("score")
    guide = deployment_guide(str(project["id"]))

    if kind == "live":
        subject = f"{name} is live — source and deployment handoff"
        heading = "Your website is live."
        lead = "Payment/publication is complete. The generated source remains available in your Project Visibility dashboard."
    else:
        subject = f"{name} is ready — preview, source and GitHub deployment guide"
        heading = "Your website is ready for review."
        lead = "Generation and quality checks are complete. Review the private preview before payment, then publish the exact approved version."

    live_block = f'<p><a href="{html.escape(public_url, quote=True)}">Open live website</a></p>' if public_url else ""
    score_block = f"<p><strong>Visual QA:</strong> {html.escape(str(qa_score))}/100</p>" if qa_score is not None else ""
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:720px;margin:auto;color:#102923;line-height:1.55">
      <h1>{html.escape(heading)}</h1>
      <p>{html.escape(lead)}</p>
      {score_block}
      {live_block}
      <p><a href="{html.escape(DASHBOARD_URL, quote=True)}">Open Project Visibility dashboard</a></p>
      <h2>GitHub deployment handoff</h2>
      <p>The dashboard contains the source ZIP. The included deployment guide explains how to publish the same source in your own GitHub repository and enable GitHub Pages.</p>
      <pre style="white-space:pre-wrap;background:#f3f7f5;padding:18px;border-radius:12px">{html.escape(guide)}</pre>
      <p style="color:#64766f">Internal delivery repo: {html.escape(core.GITHUB_OWNER + '/' + repo)}</p>
    </div>
    """
    body_text = f"{heading}\n\n{lead}\n\nDashboard: {DASHBOARD_URL}\n\n{guide}"
    return subject, body_html, body_text


def _notification_exists(project_id: str, kind: str, recipient: str) -> bool:
    ensure_notification_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT status FROM project_notifications WHERE project_id=? AND kind=? AND recipient=?",
            (project_id, kind, recipient),
        ).fetchone()
    return bool(row and row["status"] == "sent")


def _store(project_id: str, kind: str, recipient: str, status: str, *, provider_id: str = "", error: str = "") -> None:
    ensure_notification_schema()
    now = core.now_iso()
    with core.db() as con:
        con.execute(
            """
            INSERT INTO project_notifications(project_id,kind,recipient,status,provider_id,error,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id,kind,recipient) DO UPDATE SET
              status=excluded.status,provider_id=excluded.provider_id,error=excluded.error,updated_at=excluded.updated_at
            """,
            (project_id, kind, recipient, status, provider_id or None, error[:700] or None, now, now),
        )


async def send_project_email(project_id: str, kind: str, *, force: bool = False) -> dict[str, Any]:
    project = _project_context(project_id)
    if not project:
        return {"sent": False, "reason": "project_not_found"}
    recipient = _recipient(project)
    if not recipient:
        return {"sent": False, "reason": "recipient_missing"}
    if not force and _notification_exists(project_id, kind, recipient):
        return {"sent": True, "already_sent": True, "recipient": recipient}
    if not RESEND_API_KEY:
        _store(project_id, kind, recipient, "not_configured", error="RESEND_API_KEY is not configured")
        return {"sent": False, "reason": "email_not_configured", "recipient": recipient}

    subject, body_html, body_text = _message(project, kind)
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [recipient],
        "subject": subject,
        "html": body_html,
        "text": body_text,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(response.text[:500])
        data = response.json()
        provider_id = str(data.get("id") or "")
        _store(project_id, kind, recipient, "sent", provider_id=provider_id)
        return {"sent": True, "recipient": recipient, "provider_id": provider_id}
    except Exception as exc:
        _store(project_id, kind, recipient, "failed", error=str(exc))
        return {"sent": False, "reason": "delivery_failed", "recipient": recipient, "error": str(exc)[:300]}


@core.app.get("/projects/{project_id}/handoff")
async def project_handoff(project_id: str, user_id: str = Depends(core.current_user)):
    ensure_notification_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT id FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        notices = con.execute(
            "SELECT kind,recipient,status,provider_id,error,updated_at FROM project_notifications WHERE project_id=? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
    if not row:
        raise HTTPException(404, "Project not found")
    return {
        "project_id": project_id,
        "email_enabled": bool(RESEND_API_KEY),
        "guide": deployment_guide(project_id),
        "notifications": [dict(x) for x in notices],
    }


@core.app.post("/projects/{project_id}/handoff-email")
async def send_handoff_email(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        row = con.execute(
            "SELECT id,status,repo_name,last_audit_json FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    if not row["repo_name"]:
        raise HTTPException(409, "Handoff becomes available after generation is complete")
    audit = _audit(row["last_audit_json"])
    kind = "live" if audit.get("public_live") else "build_ready"
    result = await send_project_email(project_id, kind, force=True)
    if not result.get("sent"):
        reason = result.get("reason") or "delivery_failed"
        if reason == "email_not_configured":
            raise HTTPException(503, "Email delivery is not configured. Set RESEND_API_KEY first.")
        raise HTTPException(502, result.get("error") or "Could not send handoff email")
    return result
