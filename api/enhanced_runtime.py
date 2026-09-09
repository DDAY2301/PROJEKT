"""Runtime enhancements for the autonomous website agent.

This module patches the generation coroutine in api.main without duplicating the
API routes. It adds explicit build states, automatic GitHub Pages publishing and
guarantees that background task failures are persisted as a project status.
"""

import json
import re

import api.main as core
from api.pages_publish import publish_generated_site


def set_status(project_id: str, status: str) -> None:
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (status, core.now_iso(), project_id),
        )


async def generate_project_observable(project_id: str):
    try:
        with core.db() as con:
            row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return
            config = json.loads(row["config_json"])

        set_status(project_id, "designing")
        spec = await core.design_site(config)

        set_status(project_id, "building")
        files = await core.build_files(config, spec)

        set_status(project_id, "auditing")
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        issues = audit1["issues"] + audit2.get("issues", [])

        attempts = 0
        while any(i.get("severity") in {"critical", "high"} for i in issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
            attempts += 1
            set_status(project_id, "fixing")
            files = await core.fix_files(files, issues, config)

            set_status(project_id, "auditing")
            audit1 = core.static_audit(files)
            audit2 = await core.ai_audit(files, config)
            issues = audit1["issues"] + audit2.get("issues", [])

        repo_name = re.sub(
            r"[^a-z0-9-]+",
            "-",
            (core.GITHUB_OUTPUT_PREFIX + config["name"]).lower(),
        ).strip("-")[:90]

        set_status(project_id, "publishing")
        await core.github_put_bundle(repo_name, files, f"Agent build for {config['name']}")
        await publish_generated_site(repo_name)

        final_status = "ready" if not any(
            i.get("severity") in {"critical", "high"} for i in issues
        ) else "needs_review"

        with core.db() as con:
            con.execute(
                "UPDATE projects SET status=?,repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (
                    final_status,
                    repo_name,
                    json.dumps({"issues": issues}, ensure_ascii=False),
                    attempts,
                    core.now_iso(),
                    project_id,
                ),
            )
    except Exception as exc:
        failure = {
            "issues": [
                {
                    "severity": "critical",
                    "code": "BUILD_FAILED",
                    "file": "",
                    "message": str(exc)[:700],
                }
            ]
        }
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='failed',last_audit_json=?,updated_at=? WHERE id=?",
                (json.dumps(failure, ensure_ascii=False), core.now_iso(), project_id),
            )


# Route functions in api.main resolve this name from the module at runtime, so
# replacing it here upgrades create/patch/audit background tasks as well as the
# scheduler without duplicating endpoints.
core.generate_project = generate_project_observable
