"""Payment gate for new website projects.

When Stripe is configured, creating a project stores the brief and waits for a
successful Checkout payment before the autonomous generation task starts.
When Stripe is not configured, local development keeps the historical immediate
build behaviour.
"""

import asyncio
import json
import uuid

from fastapi import Depends

import api.main as core
import api.billing as billing


# Remove the original POST /projects route registered by api.main. Revisions,
# reads and other project routes remain untouched.
core.app.router.routes[:] = [
    route
    for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/projects"
        and "POST" in (getattr(route, "methods", set()) or set())
    )
]


@core.app.post("/projects")
async def create_project_with_payment_gate(
    data: core.ProjectCreate,
    user_id: str = Depends(core.current_user),
):
    pid = str(uuid.uuid4())
    cfg = data.model_dump(mode="json")
    requires_payment = billing.package_is_configured(data.package)
    initial_status = "awaiting_payment" if requires_payment else "queued"

    with core.db() as con:
        con.execute(
            "INSERT INTO projects(id,user_id,package,status,name,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                pid,
                user_id,
                data.package,
                initial_status,
                data.name,
                json.dumps(cfg, ensure_ascii=False),
                core.now_iso(),
                core.now_iso(),
            ),
        )

    if not requires_payment:
        asyncio.create_task(core.generate_project(pid))

    return {
        "id": pid,
        "status": initial_status,
        "payment_required": requires_payment,
    }
