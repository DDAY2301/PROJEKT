"""Customer project lifecycle controls for production use.

Provides cooperative cancellation plus non-destructive archive/restore. Archive
state is stored separately from the project build status so a customer can
restore the exact prior final state without rebuilding the site.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

import api.main as core
import api.production_queue as production_queue

ACTIVE = {
    "queued",
    "designing",
    "building",
    "auditing",
    "visual_qa",
    "fixing",
    "repository_ready",
    "publishing",
    "revising",
    "cancel_requested",
}


def ensure_schema() -> None:
    with core.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS project_lifecycle (
              project_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              archived INTEGER NOT NULL DEFAULT 0,
              prior_status TEXT NOT NULL DEFAULT '',
              archived_at TEXT,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id),
              FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )


def lifecycle_for(project_id: str) -> dict:
    ensure_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT archived,prior_status,archived_at,updated_at FROM project_lifecycle WHERE project_id=?",
            (project_id,),
        ).fetchone()
    if not row:
        return {"archived": False, "prior_status": "", "archived_at": None, "updated_at": None}
    return {
        "archived": bool(row["archived"]),
        "prior_status": str(row["prior_status"] or ""),
        "archived_at": row["archived_at"],
        "updated_at": row["updated_at"],
    }


def _owned(project_id: str, user_id: str):
    with core.db() as con:
        row = con.execute(
            "SELECT id,status,repo_name,last_audit_json FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return row


@core.app.post("/projects/{project_id}/cancel")
async def cancel_project(project_id: str, user_id: str = Depends(core.current_user)):
    row = _owned(project_id, user_id)
    status = str(row["status"] or "")
    if status in {"ready", "ready_for_payment", "payment_pending", "needs_review", "failed", "cancelled", "archived"}:
        return {
            "project_id": project_id,
            "status": status,
            "cancelled": status == "cancelled",
            "already_finished": True,
        }

    queue_state = production_queue.request_cancel(project_id)
    new_status = "cancel_requested" if queue_state == "cancel_requested" else "cancelled"
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (new_status, core.now_iso(), project_id),
        )
    return {
        "project_id": project_id,
        "status": new_status,
        "queue_state": queue_state,
        "cancelled": new_status == "cancelled",
    }


@core.app.post("/projects/{project_id}/archive")
async def archive_project(project_id: str, user_id: str = Depends(core.current_user)):
    ensure_schema()
    row = _owned(project_id, user_id)
    status = str(row["status"] or "")
    if status in ACTIVE:
        raise HTTPException(409, "Active projects must be cancelled or completed before archiving")

    existing = lifecycle_for(project_id)
    if existing["archived"]:
        return {"project_id": project_id, **existing}

    now = core.now_iso()
    prior = status if status != "archived" else str(existing.get("prior_status") or "needs_review")
    with core.db() as con:
        con.execute(
            """INSERT INTO project_lifecycle(project_id,user_id,archived,prior_status,archived_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
                 user_id=excluded.user_id,archived=1,prior_status=excluded.prior_status,
                 archived_at=excluded.archived_at,updated_at=excluded.updated_at""",
            (project_id, user_id, 1, prior, now, now),
        )
        con.execute(
            "UPDATE projects SET status='archived',updated_at=? WHERE id=?",
            (now, project_id),
        )
    return {
        "project_id": project_id,
        "archived": True,
        "prior_status": prior,
        "archived_at": now,
    }


@core.app.post("/projects/{project_id}/restore")
async def restore_project(project_id: str, user_id: str = Depends(core.current_user)):
    ensure_schema()
    _owned(project_id, user_id)
    lifecycle = lifecycle_for(project_id)
    if not lifecycle["archived"]:
        with core.db() as con:
            current = con.execute("SELECT status FROM projects WHERE id=?", (project_id,)).fetchone()
        return {
            "project_id": project_id,
            "archived": False,
            "status": str(current["status"] if current else ""),
        }

    target = str(lifecycle.get("prior_status") or "needs_review")
    if target in ACTIVE or target in {"archived", ""}:
        target = "needs_review"
    now = core.now_iso()
    with core.db() as con:
        con.execute(
            "UPDATE project_lifecycle SET archived=0,updated_at=? WHERE project_id=?",
            (now, project_id),
        )
        con.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (target, now, project_id),
        )
    return {
        "project_id": project_id,
        "archived": False,
        "status": target,
    }


ensure_schema()
