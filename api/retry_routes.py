"""Recovery endpoints for customer website builds and publishing."""

import asyncio
import json
import re

from fastapi import Depends, HTTPException

import api.main as core
from api.pages_publish import PagesPermissionError, publish_generated_site, wait_for_generated_site


_publish_tasks: dict[str, asyncio.Task] = {}


def _repo_name(config: dict) -> str:
    return re.sub(
        r"[^a-z0-9-]+",
        "-",
        (core.GITHUB_OUTPUT_PREFIX + config["name"]).lower(),
    ).strip("-")[:90]


def _audit_without_publish_failures(raw: str | None) -> dict:
    try:
        audit = json.loads(raw or "{}")
    except Exception:
        audit = {}
    issues = []
    for item in audit.get("issues") or []:
        code = str(item.get("code") or "")
        message = str(item.get("message") or "")
        if code in {"GITHUB_PAGES_PERMISSION", "PAGES_PROPAGATING", "PUBLISH_RETRY_FAILED"}:
            continue
        if code == "BUILD_FAILED" and "public website publishing" in message.lower():
            continue
        issues.append(item)
    audit["issues"] = issues
    audit.pop("publish_action_required", None)
    return audit


async def _publish_existing(project_id: str) -> None:
    with core.db() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return
        config = json.loads(row["config_json"])
        repo_name = row["repo_name"] or _repo_name(config)
        audit = _audit_without_publish_failures(row["last_audit_json"])
        con.execute(
            "UPDATE projects SET status='publishing',repo_name=?,updated_at=? WHERE id=?",
            (repo_name, core.now_iso(), project_id),
        )

    public_url = f"https://{core.GITHUB_OWNER.lower()}.github.io/{repo_name}/"
    try:
        public_url = await publish_generated_site(repo_name)
        live = await wait_for_generated_site(public_url, seconds=90)
        if not live:
            audit["issues"].append({
                "severity": "low",
                "code": "PAGES_PROPAGATING",
                "file": "",
                "message": "GitHub Pages is enabled and the first public deployment is still propagating.",
            })
        audit.update({
            "repository_ready": True,
            "public_url": public_url,
            "public_live": live,
        })
        audit.pop("publish_action_required", None)
        final_status = "ready" if not any(
            i.get("severity") in {"critical", "high"} for i in audit["issues"]
        ) else "needs_review"
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status=?,repo_name=?,last_audit_json=?,updated_at=? WHERE id=?",
                (final_status, repo_name, json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
            )
    except PagesPermissionError as exc:
        audit["issues"].append({
            "severity": "medium",
            "code": "GITHUB_PAGES_PERMISSION",
            "file": "",
            "message": str(exc)[:700],
        })
        audit.update({
            "repository_ready": True,
            "public_url": public_url,
            "public_live": False,
            "publish_action_required": "github_pages_permission",
        })
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='needs_review',repo_name=?,last_audit_json=?,updated_at=? WHERE id=?",
                (repo_name, json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
            )
    except Exception as exc:
        audit["issues"].append({
            "severity": "critical",
            "code": "PUBLISH_RETRY_FAILED",
            "file": "",
            "message": str(exc)[:700],
        })
        audit.update({"repository_ready": True, "public_url": public_url, "public_live": False})
        audit.pop("publish_action_required", None)
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='failed',repo_name=?,last_audit_json=?,updated_at=? WHERE id=?",
                (repo_name, json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
            )


async def _publish_task_runner(project_id: str) -> None:
    try:
        await _publish_existing(project_id)
    finally:
        _publish_tasks.pop(project_id, None)


def _ensure_publish_task(project_id: str) -> bool:
    """Start publishing if it is not actually running.

    Returns True when a new task was started and False when an existing task is
    already active. The in-memory registry intentionally resets on process
    restart; a database row left in `publishing` can therefore be resumed by the
    next request instead of becoming permanently stuck.
    """
    existing = _publish_tasks.get(project_id)
    if existing and not existing.done():
        return False
    task = asyncio.create_task(_publish_task_runner(project_id))
    _publish_tasks[project_id] = task
    return True


@core.app.post("/projects/{project_id}/retry")
async def retry_project(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        row = con.execute(
            "SELECT id,status FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        if row["status"] in {"designing", "building", "auditing", "fixing", "publishing", "revising", "queued"}:
            raise HTTPException(409, "A build is already running")
        con.execute(
            "UPDATE projects SET status='queued',last_audit_json=NULL,auto_fix_attempts=0,updated_at=? WHERE id=?",
            (core.now_iso(), project_id),
        )
    asyncio.create_task(core.generate_project(project_id))
    return {"id": project_id, "status": "queued"}


@core.app.post("/projects/{project_id}/publish")
async def publish_project_only(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        row = con.execute(
            "SELECT status,config_json,repo_name FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

        # Build/revision stages are genuinely incompatible with a publish-only
        # request. `publishing` is handled separately and is intentionally
        # idempotent so duplicate clicks never become a user-facing 409.
        if row["status"] in {"designing", "building", "auditing", "fixing", "revising", "queued"}:
            raise HTTPException(409, "A website build is currently running")

        config = json.loads(row["config_json"])
        repo_name = row["repo_name"] or _repo_name(config)
        con.execute(
            "UPDATE projects SET status='publishing',repo_name=?,updated_at=? WHERE id=?",
            (repo_name, core.now_iso(), project_id),
        )

    started = _ensure_publish_task(project_id)
    return {
        "id": project_id,
        "status": "publishing",
        "repo_name": repo_name,
        "already_running": not started,
    }
