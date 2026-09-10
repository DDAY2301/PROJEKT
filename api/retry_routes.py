"""Retry endpoint for failed customer website builds."""

import asyncio

from fastapi import Depends, HTTPException

import api.main as core


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
