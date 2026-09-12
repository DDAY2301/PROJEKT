"""Project creation with post-build payment gating.

All projects are generated and quality-checked before payment. If Stripe is
configured, the finished source is held unpublished until payment succeeds.
Only after payment does the existing generated repository get published live.

A narrowly scoped sandbox bypass exists for the dedicated QA account
maj@klemec.org. It is active only when the configured Stripe key is a TEST key.
"""

import asyncio
import json
import uuid

from fastapi import Depends

import api.main as core
import api.billing as billing


TEST_BYPASS_EMAILS = {"maj@klemec.org"}


def sandbox_payment_bypass(user_id: str) -> bool:
    if not billing.STRIPE_SECRET_KEY.startswith("sk_test_"):
        return False
    with core.db() as con:
        row = con.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    email = str(row["email"] if row else "").strip().lower()
    return email in TEST_BYPASS_EMAILS


# Replace the original POST /projects route so project creation always starts a
# build immediately. Payment is enforced only after QA and repository creation.
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
    data: core.ProjectCreate,
    user_id: str = Depends(core.current_user),
):
    pid = str(uuid.uuid4())
    cfg = data.model_dump(mode="json")
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

    asyncio.create_task(core.generate_project(pid))

    return {
        "id": pid,
        "status": "queued",
        "payment_required": payment_required,
        "payment_bypassed": bypass,
        "payment_stage": "after_build",
    }
