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


def _schedule_publish(project_id: str) -> tuple[asyncio.Task, bool]:
    existing = _publish_tasks.get(project_id)
    if existing is not None and not existing.done():
        return existing, False

    task = asyncio.create_task(_publish_existing(project_id))
    _publish_tasks[project_id] = task

    def _cleanup(done_task: asyncio.Task) -> None:
        if _publish_tasks.get(project_id) is done_task:
            _publish_tasks.pop(project_id, None)

    task.add_done_callback(_cleanup)
    return task, True


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
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='failed',repo_name=?,last_audit_json=?,updated_at=? WHERE id=?",
                (repo_name, json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
            )


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

        if row["status"] in {"designing", "building", "auditing", "fixing", "revising", "queued"}:
            raise HTTPException(409, "A website build or revision is already running")

        config = json.loads(row["config_json"])
        repo_name = row["repo_name"] or _repo_name(config)

        # Publishing is intentionally idempotent. If this process already owns
        # an active publish task, return its state instead of 409. If the DB says
        # publishing but the service has restarted, there is no in-memory task;
        # schedule a fresh publish-only recovery against the existing repo.
        existing = _publish_tasks.get(project_id)
        if row["status"] == "publishing" and existing is not None and not existing.done():
            return {
                "id": project_id,
                "status": "publishing",
                "repo_name": repo_name,
                "already_running": True,
            }

        con.execute(
            "UPDATE projects SET status='publishing',repo_name=?,updated_at=? WHERE id=?",
            (repo_name, core.now_iso(), project_id),
        )

    _, started = _schedule_publish(project_id)
    return {
        "id": project_id,
        "status": "publishing",
        "repo_name": repo_name,
        "already_running": not started,
        "resumed": row["status"] == "publishing" and started,
    }
