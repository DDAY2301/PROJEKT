"""Project creation with post-build payment gating and stable build control.

Projects can now be created in a deferred state so the browser can upload all
customer media before generation starts. The explicit build endpoint is
idempotent and serializes heavy local builds, which prevents accidental double
submits from launching multiple Ollama/Visual-QA jobs at the same time.

Payment is still enforced only after QA and repository creation. A narrowly
scoped sandbox bypass exists for maj@klemec.org when Stripe is using sk_test_.
"""

import asyncio
import json
import uuid

from fastapi import Depends, HTTPException

import api.main as core
import api.billing as billing


TEST_BYPASS_EMAILS = {"maj@klemec.org"}
ACTIVE_BUILD_STATUSES = {
    "designing",
    "building",
    "auditing",
    "visual_qa",
    "fixing",
    "repository_ready",
    "publishing",
}
FINAL_OR_HELD_STATUSES = {
    "ready",
    "ready_for_payment",
    "payment_pending",
}

# One heavy website generation at a time is the safest default for the local
# GPU worker. Different users can still queue projects; they are processed in
# order without competing for VRAM.
_BUILD_SEMAPHORE = asyncio.Semaphore(1)
_ACTIVE_TASKS: set[str] = set()


class ProjectCreateControlled(core.ProjectCreate):
    defer_build: bool = False


def sandbox_payment_bypass(user_id: str) -> bool:
    if not billing.STRIPE_SECRET_KEY.startswith("sk_test_"):
        return False
    with core.db() as con:
        row = con.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    email = str(row["email"] if row else "").strip().lower()
    return email in TEST_BYPASS_EMAILS


async def _run_project_once(project_id: str) -> None:
    if project_id in _ACTIVE_TASKS:
        return
    _ACTIVE_TASKS.add(project_id)
    try:
        async with _BUILD_SEMAPHORE:
            await core.generate_project(project_id)
    finally:
        _ACTIVE_TASKS.discard(project_id)


def launch_project(project_id: str) -> bool:
    """Launch one project if this process is not already working on it."""
    if project_id in _ACTIVE_TASKS:
        return False
    asyncio.create_task(_run_project_once(project_id))
    return True


# Replace the original POST /projects route. New clients can set defer_build so
# media upload completes before generation. Older clients keep the historical
# immediate-start behaviour because defer_build defaults to False.
core.app.router.routes[:] = [
    route
    for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/projects"
        and "POST" in (getattr(route, "methods", set()) or set())
    )
]


@core.app.post("/projects")
async def create_project_with_postbuild_payment(
    data: ProjectCreateControlled,
    user_id: str = Depends(core.current_user),
):
    pid = str(uuid.uuid4())
    cfg = data.model_dump(mode="json", exclude={"defer_build"})
    bypass = sandbox_payment_bypass(user_id)
    payment_required = billing.package_is_configured(data.package) and not bypass

    with core.db() as con:
        con.execute(
            "INSERT INTO projects(id,user_id,package,status,name,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                pid,
                user_id,
                data.package,
                "queued",
                data.name,
                json.dumps(cfg, ensure_ascii=False),
                core.now_iso(),
                core.now_iso(),
            ),
        )

    if not data.defer_build:
        launch_project(pid)

    return {
        "id": pid,
        "status": "queued",
        "deferred": bool(data.defer_build),
        "payment_required": payment_required,
        "payment_bypassed": bypass,
        "payment_stage": "after_build",
    }


@core.app.post("/projects/{project_id}/build")
async def start_project_build(
    project_id: str,
    user_id: str = Depends(core.current_user),
):
    """Start generation exactly once after brief and media have been saved."""
    with core.db() as con:
        row = con.execute(
            "SELECT id,status FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")

    current = str(row["status"] or "queued")
    if current in FINAL_OR_HELD_STATUSES:
        return {"id": project_id, "status": current, "started": False, "already_finished": True}
    if current in ACTIVE_BUILD_STATUSES or project_id in _ACTIVE_TASKS:
        return {"id": project_id, "status": current, "started": False, "already_running": True}

    with core.db() as con:
        con.execute(
            "UPDATE projects SET status='queued',updated_at=? WHERE id=?",
            (core.now_iso(), project_id),
        )
    started = launch_project(project_id)
    return {"id": project_id, "status": "queued", "started": started}


async def _recover_interrupted_projects(project_ids: list[str]) -> None:
    # Run through the same serialized worker. A process restart can otherwise
    # leave a project forever showing Visual QA even though no task exists.
    for project_id in project_ids:
        await _run_project_once(project_id)


@core.app.on_event("startup")
async def recover_interrupted_builds() -> None:
    with core.db() as con:
        rows = con.execute(
            "SELECT id FROM projects WHERE status IN ('designing','building','auditing','visual_qa','fixing','repository_ready','publishing') ORDER BY updated_at ASC"
        ).fetchall()
        project_ids = [str(row["id"]) for row in rows]
        for project_id in project_ids:
            con.execute(
                "UPDATE projects SET status='queued',updated_at=? WHERE id=?",
                (core.now_iso(), project_id),
            )
    if project_ids:
        asyncio.create_task(_recover_interrupted_projects(project_ids))
