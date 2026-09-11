"""Runtime enhancements for the autonomous website agent.

This module patches the generation coroutine in api.main without duplicating the
API routes. It adds explicit build states, payment gating, uploaded-media
injection, automatic GitHub Pages publishing, a best-effort live deployment
check and persistent failure reporting.
"""

import json
import logging
import re
from pathlib import Path

import api.main as core
import api.billing as billing
import api.media as media
from api.pages_publish import PagesPermissionError, publish_generated_site, wait_for_generated_site

logger = logging.getLogger("project_visibility.build")


def set_status(project_id: str, status: str) -> None:
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (status, core.now_iso(), project_id),
        )


def repo_name_for(config: dict) -> str:
    return re.sub(
        r"[^a-z0-9-]+",
        "-",
        (core.GITHUB_OUTPUT_PREFIX + config["name"]).lower(),
    ).strip("-")[:90]


def _inject_uploaded_image_metadata(project_id: str, config: dict) -> list[dict]:
    rows = media.images_for_project(project_id)
    images = []
    for row in rows:
        images.append(
            {
                "id": row["id"],
                "repo_path": row["repo_path"],
                "alt_text": row["alt_text"] or row["original_name"],
                "placement": row["placement"],
                "original_name": row["original_name"],
                "stored_path": row["stored_path"],
            }
        )
    config["uploaded_images"] = [
        {k: v for k, v in image.items() if k != "stored_path"}
        for image in images
    ]
    return images


def _attach_uploaded_image_bytes(files: dict, images: list[dict]) -> None:
    for image in images:
        try:
            data = Path(image["stored_path"]).read_bytes()
        except OSError as exc:
            logger.warning("Could not read uploaded image path=%s error=%s", image.get("stored_path"), exc)
            continue
        files[image["repo_path"]] = data


async def generate_project_observable(project_id: str):
    phase = "preparing"
    repo_name = None
    try:
        with core.db() as con:
            row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return
            config = json.loads(row["config_json"])

        if billing.payments_required(project_id, config.get("package", "")):
            set_status(project_id, "awaiting_payment")
            logger.info("Build waiting for payment project=%s package=%s", project_id, config.get("package"))
            return

        uploaded_images = _inject_uploaded_image_metadata(project_id, config)

        phase = "structure"
        set_status(project_id, "designing")
        spec = await core.design_site(config)

        phase = "website build"
        set_status(project_id, "building")
        files = await core.build_files(config, spec)

        phase = "quality review"
        set_status(project_id, "auditing")
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        issues = audit1["issues"] + audit2.get("issues", [])

        attempts = 0
        while any(i.get("severity") in {"critical", "high"} for i in issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
            attempts += 1
            phase = f"automatic repair {attempts}"
            set_status(project_id, "fixing")
            files = await core.fix_files(files, issues, config)

            phase = "quality re-check"
            set_status(project_id, "auditing")
            audit1 = core.static_audit(files)
            audit2 = await core.ai_audit(files, config)
            issues = audit1["issues"] + audit2.get("issues", [])

        # Binary assets are added only after text QA so the model never receives
        # image bytes and static text checks remain deterministic.
        _attach_uploaded_image_bytes(files, uploaded_images)

        repo_name = repo_name_for(config)

        phase = "GitHub publishing"
        set_status(project_id, "publishing")
        await core.github_put_bundle(repo_name, files, f"Agent build for {config['name']}")

        # Persist repository delivery immediately. Public Pages enablement is a
        # separate concern and must never erase an otherwise successful build.
        with core.db() as con:
            con.execute(
                "UPDATE projects SET repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (
                    repo_name,
                    json.dumps({
                        "issues": issues,
                        "repository_ready": True,
                        "public_url": None,
                        "public_live": False,
                        "uploaded_images": len(uploaded_images),
                    }, ensure_ascii=False),
                    attempts,
                    core.now_iso(),
                    project_id,
                ),
            )

        phase = "public website publishing"
        try:
            public_url = await publish_generated_site(repo_name)
        except PagesPermissionError as exc:
            public_url = f"https://{core.GITHUB_OWNER.lower()}.github.io/{repo_name}/"
            issues.append({
                "severity": "medium",
                "code": "GITHUB_PAGES_PERMISSION",
                "file": "",
                "message": str(exc)[:700],
            })
            with core.db() as con:
                con.execute(
                    "UPDATE projects SET status='needs_review',repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                    (
                        repo_name,
                        json.dumps({
                            "issues": issues,
                            "repository_ready": True,
                            "public_url": public_url,
                            "public_live": False,
                            "publish_action_required": "github_pages_permission",
                            "uploaded_images": len(uploaded_images),
                        }, ensure_ascii=False),
                        attempts,
                        core.now_iso(),
                        project_id,
                    ),
                )
            logger.warning("Website code delivered but Pages permission is missing project=%s repo=%s", project_id, repo_name)
            return

        live = await wait_for_generated_site(public_url, seconds=90)
        if not live:
            issues.append({
                "severity": "low",
                "code": "PAGES_PROPAGATING",
                "file": "",
                "message": "GitHub Pages was enabled but the public edge is still propagating.",
            })

        final_status = "ready" if not any(
            i.get("severity") in {"critical", "high"} for i in issues
        ) else "needs_review"

        with core.db() as con:
            con.execute(
                "UPDATE projects SET status=?,repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (
                    final_status,
                    repo_name,
                    json.dumps({
                        "issues": issues,
                        "repository_ready": True,
                        "public_url": public_url,
                        "public_live": live,
                        "uploaded_images": len(uploaded_images),
                    }, ensure_ascii=False),
                    attempts,
                    core.now_iso(),
                    project_id,
                ),
            )
        logger.info("Website build completed project=%s status=%s repo=%s", project_id, final_status, repo_name)
    except Exception as exc:
        logger.exception("Website build failed project=%s phase=%s", project_id, phase)
        detail = str(exc).strip() or exc.__class__.__name__
        failure = {
            "failure_stage": phase,
            "error_type": exc.__class__.__name__,
            "issues": [
                {
                    "severity": "critical",
                    "code": "BUILD_FAILED",
                    "file": "",
                    "message": f"Build failed during {phase}: {detail}"[:700],
                }
            ],
        }
        with core.db() as con:
            if repo_name:
                con.execute(
                    "UPDATE projects SET status='failed',repo_name=?,last_audit_json=?,updated_at=? WHERE id=?",
                    (repo_name, json.dumps(failure, ensure_ascii=False), core.now_iso(), project_id),
                )
            else:
                con.execute(
                    "UPDATE projects SET status='failed',last_audit_json=?,updated_at=? WHERE id=?",
                    (json.dumps(failure, ensure_ascii=False), core.now_iso(), project_id),
                )


core.generate_project = generate_project_observable
