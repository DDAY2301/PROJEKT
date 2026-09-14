"""Post-build handoff wrapper.

After generation completes, add a deployment guide to the generated repository
and send the appropriate customer email. These handoff tasks are best-effort and
must never break generation, payment or publication.
"""

from __future__ import annotations

import json
import logging

import api.main as core
import api.notifications as notifications

logger = logging.getLogger("project_visibility.handoff")
_base_generate_project = core.generate_project


def _audit(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _finalize_handoff(project_id: str) -> None:
    with core.db() as con:
        row = con.execute(
            "SELECT id,status,repo_name,last_audit_json FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
    if not row or not row["repo_name"]:
        return

    guide = notifications.deployment_guide(project_id)
    if guide:
        try:
            await core.github_put_bundle(
                str(row["repo_name"]),
                {"PROJECT-VISIBILITY-DEPLOYMENT.md": guide},
                "Add Project Visibility deployment handoff",
            )
        except Exception as exc:
            logger.warning("Could not add deployment guide project=%s error=%s", project_id, exc)

    audit = _audit(row["last_audit_json"])
    kind = None
    if audit.get("public_live"):
        kind = "live"
    elif row["status"] in {"ready_for_payment", "repository_ready"} or audit.get("repository_ready"):
        kind = "build_ready"

    if kind:
        try:
            result = await notifications.send_project_email(project_id, kind)
            if not result.get("sent") and result.get("reason") not in {"email_not_configured", "recipient_missing"}:
                logger.warning("Customer handoff email was not sent project=%s result=%s", project_id, result)
        except Exception as exc:
            logger.warning("Customer handoff email failed project=%s error=%s", project_id, exc)


async def generate_project_with_handoff(project_id: str):
    try:
        return await _base_generate_project(project_id)
    finally:
        try:
            await _finalize_handoff(project_id)
        except Exception:
            logger.exception("Post-build handoff failed project=%s", project_id)


core.generate_project = generate_project_with_handoff
