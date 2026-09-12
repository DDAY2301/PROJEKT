"""Observable generation runtime with media, visual QA and post-build payment.

The runtime generates and quality-checks the complete website first. When Stripe
is configured, the finished source is then held unpublished until payment is
confirmed. After payment, the already-generated repository is published live
without rebuilding the website.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import api.billing as billing
import api.main as core
import api.media as media
import api.visual_qa as visual_qa
from api.pages_publish import PagesPermissionError, publish_generated_site, wait_for_generated_site

logger = logging.getLogger("project_visibility.build")

TEST_BYPASS_EMAILS = {"maj@klemec.org"}


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


def _sandbox_payment_bypass(user_id: str) -> bool:
    if not billing.STRIPE_SECRET_KEY.startswith("sk_test_"):
        return False
    with core.db() as con:
        row = con.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    email = str(row["email"] if row else "").strip().lower()
    return email in TEST_BYPASS_EMAILS


def _inject_uploaded_image_metadata(project_id: str, config: dict) -> list[dict[str, Any]]:
    rows = media.images_for_project(project_id)
    images: list[dict[str, Any]] = []
    public_images: list[dict[str, Any]] = []
    for row in rows:
        variants = row.get("variants") or []
        full = {
            "id": row["id"],
            "repo_path": row["repo_path"],
            "alt_text": row["alt_text"] or row["original_name"],
            "placement": row["placement"],
            "original_name": row["original_name"],
            "stored_path": row["stored_path"],
            "width": int(row.get("width") or 0),
            "height": int(row.get("height") or 0),
            "focal_x": float(row.get("focal_x") or 50),
            "focal_y": float(row.get("focal_y") or 50),
            "kind": row.get("kind") or "image",
            "variants": variants,
        }
        images.append(full)
        public_images.append({
            **{k: v for k, v in full.items() if k not in {"stored_path", "variants"}},
            "variants": [
                {k: v for k, v in variant.items() if k != "stored_path"}
                for variant in variants
            ],
        })
    config["uploaded_images"] = public_images
    return images


def _attach_uploaded_image_bytes(files: dict[str, Any], images: list[dict[str, Any]]) -> None:
    attached: set[str] = set()
    for image in images:
        variants = image.get("variants") or []
        for variant in variants:
            repo_path = str(variant.get("repo_path") or "")
            stored_path = str(variant.get("stored_path") or "")
            if not repo_path or not stored_path or repo_path in attached:
                continue
            try:
                files[repo_path] = Path(stored_path).read_bytes()
                attached.add(repo_path)
            except OSError as exc:
                logger.warning("Could not read image variant path=%s error=%s", stored_path, exc)
        repo_path = str(image.get("repo_path") or "")
        stored_path = str(image.get("stored_path") or "")
        if repo_path and stored_path and repo_path not in attached:
            try:
                files[repo_path] = Path(stored_path).read_bytes()
                attached.add(repo_path)
            except OSError as exc:
                logger.warning("Could not read uploaded image path=%s error=%s", stored_path, exc)


def _severe(issues: list[dict[str, Any]]) -> bool:
    return any(item.get("severity") in {"critical", "high"} for item in issues)


def _visual_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": bool(report.get("available")),
        "passed": bool(report.get("passed")),
        "score": report.get("score"),
        "pages_checked": int(report.get("pages_checked") or 0),
        "render_count": int(report.get("render_count") or 0),
        "version": report.get("version") or "visual-qa-v1",
        "screenshots": report.get("screenshots") or [],
    }


def _audit_payload(
    issues: list[dict[str, Any]],
    visual_report: dict[str, Any],
    *,
    repository_ready: bool,
    public_url: str | None,
    public_live: bool,
    uploaded_images: int,
    extra: dict[str, Any] | None = None,
) -> str:
    data: dict[str, Any] = {
        "issues": issues,
        "repository_ready": repository_ready,
        "public_url": public_url,
        "public_live": public_live,
        "uploaded_images": uploaded_images,
        "visual_qa": _visual_summary(visual_report),
    }
    if extra:
        data.update(extra)
    return json.dumps(data, ensure_ascii=False)


def _read_audit(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["last_audit_json"] or "{}")
    except Exception:
        return {}


async def _quality_cycle(
    files: dict[str, Any],
    config: dict[str, Any],
    project_id: str,
    uploaded_images: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], int, dict[str, Any]]:
    attempts = 0
    audit1 = core.static_audit(files)
    audit2 = await core.ai_audit(files, config)
    text_issues = audit1["issues"] + audit2.get("issues", [])

    while _severe(text_issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
        attempts += 1
        set_status(project_id, "fixing")
        files = await core.fix_files(files, text_issues, config)
        set_status(project_id, "auditing")
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        text_issues = audit1["issues"] + audit2.get("issues", [])

    set_status(project_id, "visual_qa")
    visual_report = await visual_qa.audit_files(files, project_id, config, uploaded_images)
    visual_issues = list(visual_report.get("issues") or [])
    combined = text_issues + visual_issues

    while _severe(visual_issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
        attempts += 1
        set_status(project_id, "fixing")
        files = await core.fix_files(files, combined, config)
        set_status(project_id, "auditing")
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        text_issues = audit1["issues"] + audit2.get("issues", [])
        set_status(project_id, "visual_qa")
        visual_report = await visual_qa.audit_files(files, project_id, config, uploaded_images)
        visual_issues = list(visual_report.get("issues") or [])
        combined = text_issues + visual_issues

    return files, combined, attempts, visual_report


async def _publish_existing_project(project_id: str, row: Any, audit: dict[str, Any]) -> None:
    """Publish an already-generated repository after payment without rebuilding."""
    repo_name = str(row["repo_name"] or "")
    if not repo_name:
        return

    issues = list(audit.get("issues") or [])
    visual_report = dict(audit.get("visual_qa") or {})
    uploaded_images = int(audit.get("uploaded_images") or 0)

    set_status(project_id, "publishing")
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
                "UPDATE projects SET status='needs_review',last_audit_json=?,updated_at=? WHERE id=?",
                (
                    _audit_payload(
                        issues,
                        visual_report,
                        repository_ready=True,
                        public_url=public_url,
                        public_live=False,
                        uploaded_images=uploaded_images,
                        extra={"publish_action_required": "github_pages_permission", "payment_required": False},
                    ),
                    core.now_iso(),
                    project_id,
                ),
            )
        return

    live = await wait_for_generated_site(public_url, seconds=90)
    if not live:
        issues.append({
            "severity": "low",
            "code": "PAGES_PROPAGATING",
            "file": "",
            "message": "GitHub Pages was enabled but the public edge is still propagating.",
        })

    final_status = "ready" if not _severe(issues) else "needs_review"
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,last_audit_json=?,updated_at=? WHERE id=?",
            (
                final_status,
                _audit_payload(
                    issues,
                    visual_report,
                    repository_ready=True,
                    public_url=public_url,
                    public_live=live,
                    uploaded_images=uploaded_images,
                    extra={"payment_required": False, "payment_stage": "completed"},
                ),
                core.now_iso(),
                project_id,
            ),
        )


async def generate_project_observable(project_id: str):
    phase = "preparing"
    repo_name = None
    visual_report: dict[str, Any] = {"available": False, "passed": False, "screenshots": []}
    try:
        with core.db() as con:
            row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return
            config = json.loads(row["config_json"])

        audit = _read_audit(row)
        bypass = _sandbox_payment_bypass(str(row["user_id"]))
        stripe_required = billing.package_is_configured(config.get("package", "")) and not bypass

        # Payment/webhook resume path: if the site was already generated and held
        # for payment, never regenerate it. Publish the exact approved repository.
        if row["repo_name"] and audit.get("repository_ready") and not audit.get("public_live"):
            if stripe_required and not billing.project_is_paid(project_id):
                set_status(project_id, "ready_for_payment")
                return
            await _publish_existing_project(project_id, row, audit)
            return

        uploaded_images = _inject_uploaded_image_metadata(project_id, config)

        phase = "structure"
        set_status(project_id, "designing")
        spec = await core.design_site(config)

        phase = "website build"
        set_status(project_id, "building")
        files = await core.build_files(config, spec)

        phase = "quality and visual review"
        set_status(project_id, "auditing")
        files, issues, attempts, visual_report = await _quality_cycle(files, config, project_id, uploaded_images)

        _attach_uploaded_image_bytes(files, uploaded_images)
        repo_name = repo_name_for(config)

        # Store the finished source in GitHub first, but do NOT enable Pages yet.
        phase = "repository delivery"
        set_status(project_id, "repository_ready")
        await core.github_put_bundle(repo_name, files, f"Agent build for {config['name']}")

        audit_json = _audit_payload(
            issues,
            visual_report,
            repository_ready=True,
            public_url=None,
            public_live=False,
            uploaded_images=len(uploaded_images),
            extra={
                "payment_required": stripe_required,
                "payment_stage": "after_build" if stripe_required else "not_required",
                "preview_ready": True,
            },
        )
        with core.db() as con:
            con.execute(
                "UPDATE projects SET repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (repo_name, audit_json, attempts, core.now_iso(), project_id),
            )

        if stripe_required and not billing.project_is_paid(project_id):
            set_status(project_id, "ready_for_payment")
            logger.info("Website generated and held for payment project=%s repo=%s", project_id, repo_name)
            return

        # Development mode and the dedicated sandbox QA account publish without
        # charging. Production users reach this point only after payment.
        with core.db() as con:
            fresh = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        await _publish_existing_project(project_id, fresh, json.loads(audit_json))
        logger.info("Website build completed project=%s repo=%s", project_id, repo_name)
    except Exception as exc:
        logger.exception("Website build failed project=%s phase=%s", project_id, phase)
        detail = str(exc).strip() or exc.__class__.__name__
        failure = {
            "failure_stage": phase,
            "error_type": exc.__class__.__name__,
            "visual_qa": _visual_summary(visual_report),
            "issues": [{
                "severity": "critical",
                "code": "BUILD_FAILED",
                "file": "",
                "message": f"Build failed during {phase}: {detail}"[:700],
            }],
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
