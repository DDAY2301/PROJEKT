"""Observable generation runtime with media, visual QA and post-build payment.

The runtime generates and quality-checks the complete website first. When Stripe
is configured, the finished source is then held unpublished until payment is
confirmed. After payment, the already-generated repository is published live
without rebuilding the website.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import api.billing as billing
import api.main as core
import api.media as media
import api.visual_qa as visual_qa
import api.quality_originality_v2 as originality_v2
from api.pages_publish import PagesPermissionError, publish_generated_site, wait_for_generated_site

logger = logging.getLogger("project_visibility.build")
MIN_VISUAL_QA_SCORE = max(80, min(100, int(os.getenv("MIN_VISUAL_QA_SCORE", "90"))))
TEXT_REPAIR_ATTEMPTS = max(0, min(2, int(os.getenv("TEXT_REPAIR_ATTEMPTS", "1"))))
VISUAL_REPAIR_ATTEMPTS = max(0, min(2, int(os.getenv("VISUAL_REPAIR_ATTEMPTS", "1"))))
NON_MODEL_REPAIR_CODES = {
    "DESIGN_NEAR_DUPLICATE",
    "DESIGN_ENGINE_V2_MISSING",
    "DESIGN_SYSTEM_TOO_THIN",
    "DESIGN_SYSTEM_MISSING",
    "RAW_LANGUAGE_MARKER",
    "HTML_SHELL_INVALID",
    "STYLESHEET_MISSING",
    "VIEWPORT_MISSING",
    "NO_HTML",
    "SECRET",
}

TEST_BYPASS_EMAILS = {"maj@klemec.org"}


def set_status(project_id: str, status: str) -> None:
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (status, core.now_iso(), project_id),
        )


def _cancel_requested(project_id: str) -> bool:
    try:
        with core.db() as con:
            row = con.execute(
                "SELECT cancel_requested FROM production_jobs WHERE project_id=?",
                (project_id,),
            ).fetchone()
        return bool(row and int(row["cancel_requested"] or 0))
    except Exception:
        return False


def _cancel_checkpoint(project_id: str, stage: str) -> bool:
    if not _cancel_requested(project_id):
        return False
    payload = {
        "cancelled": True,
        "cancelled_stage": stage,
        "issues": [],
        "repository_ready": False,
        "public_live": False,
    }
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status='cancelled',last_audit_json=?,updated_at=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), core.now_iso(), project_id),
        )
    logger.info("Website build cancelled project=%s stage=%s", project_id, stage)
    return True


def repo_name_for(config: dict, project_id: str = "") -> str:
    base = re.sub(
        r"[^a-z0-9-]+",
        "-",
        (core.GITHUB_OUTPUT_PREFIX + str(config.get("name") or "website")).lower(),
    ).strip("-")
    suffix = re.sub(r"[^a-f0-9]", "", str(project_id).lower())[:8]
    if suffix:
        base = f"{base[:80].rstrip('-')}-{suffix}"
    return base[:90]


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


def _delivery_manifest(
    files: dict[str, Any],
    *,
    project_id: str,
    config: dict[str, Any],
    visual_report: dict[str, Any],
    originality: dict[str, Any],
) -> dict[str, Any]:
    manifest_files = []
    for path, content in sorted(files.items()):
        raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
        manifest_files.append({
            "path": path,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    design = {}
    try:
        design = json.loads(str(files.get("assets/design-manifest.json") or "{}"))
    except Exception:
        design = {}
    return {
        "project_id": project_id,
        "name": str(config.get("name") or ""),
        "organization": str(config.get("organization") or ""),
        "generated_at": core.now_iso(),
        "generator": "Project Visibility",
        "quality": {
            "visual_score": visual_report.get("score"),
            "visual_passed": visual_report.get("passed"),
            "originality": originality,
        },
        "design_system": design,
        "file_count": len(manifest_files),
        "files": manifest_files,
    }


def _attach_delivery_manifest(
    files: dict[str, Any],
    *,
    project_id: str,
    config: dict[str, Any],
    visual_report: dict[str, Any],
    originality: dict[str, Any],
) -> None:
    manifest = _delivery_manifest(
        files,
        project_id=project_id,
        config=config,
        visual_report=visual_report,
        originality=originality,
    )
    files["PROJECT-VISIBILITY-MANIFEST.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)


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


def _strip_unsupported_contact_facts(files: dict[str, Any], config: dict[str, Any]) -> int:
    brief_digits = re.sub(r"\D", "", json.dumps(config, ensure_ascii=False))
    phone_re = re.compile(r"\+\d[\d\s().-]{7,}\d")
    changed = 0

    for path, content in list(files.items()):
        if not path.endswith(".html") or not isinstance(content, str):
            continue

        def replace_phone(match: re.Match[str]) -> str:
            nonlocal changed
            digits = re.sub(r"\D", "", match.group(0))
            if digits and digits in brief_digits:
                return match.group(0)
            changed += 1
            return ""

        cleaned = phone_re.sub(replace_phone, content)
        if cleaned != content:
            # Clean up empty tel links or punctuation left behind by a removed
            # hallucinated phone number.
            cleaned = re.sub(
                r'<a([^>]*?)href=["\']tel:\s*["\']([^>]*)>\s*</a>',
                "",
                cleaned,
                flags=re.I,
            )
            cleaned = re.sub(r"\s{2,}", " ", cleaned)
            files[path] = cleaned
    return changed


def _severe(issues: list[dict[str, Any]]) -> bool:
    return any(item.get("severity") in {"critical", "high"} for item in issues)


def _model_repairable(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in issues:
        if item.get("severity") not in {"critical", "high"}:
            continue
        code = str(item.get("code") or "").upper()
        path = str(item.get("file") or "")
        if code in NON_MODEL_REPAIR_CODES:
            continue
        if not path.endswith((".html", ".css", ".js")):
            continue
        out.append(item)
    return out


def _record_interim_quality(project_id: str, issues: list[dict[str, Any]], stage: str, attempt: int) -> None:
    payload = {
        "build_stage": stage,
        "repair_attempt": attempt,
        "issues": issues[:40],
        "repository_ready": False,
        "public_live": False,
        "quality_gate_passed": False,
    }
    with core.db() as con:
        con.execute(
            "UPDATE projects SET last_audit_json=?,updated_at=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), core.now_iso(), project_id),
        )


def _quality_gate_passed(issues: list[dict[str, Any]], visual_report: dict[str, Any]) -> bool:
    if _severe(issues):
        return False
    if not visual_report.get("available") or not visual_report.get("passed"):
        return False
    score = visual_report.get("score")
    try:
        return float(score) >= MIN_VISUAL_QA_SCORE
    except (TypeError, ValueError):
        return False


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
    text_attempts = 0
    visual_attempts = 0
    _strip_unsupported_contact_facts(files, config)
    audit1 = core.static_audit(files)
    audit2 = await core.ai_audit(files, config)
    text_issues = audit1["issues"] + audit2.get("issues", [])
    _record_interim_quality(project_id, text_issues, "text_qa", 0)

    while _severe(text_issues) and text_attempts < TEXT_REPAIR_ATTEMPTS:
        repairable = _model_repairable(text_issues)
        if not repairable:
            break
        text_attempts += 1
        set_status(project_id, "fixing")
        _record_interim_quality(project_id, text_issues, "text_fixing", text_attempts)
        files = await core.fix_files(files, repairable, config)
        set_status(project_id, "auditing")
        _strip_unsupported_contact_facts(files, config)
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        text_issues = audit1["issues"] + audit2.get("issues", [])
        _record_interim_quality(project_id, text_issues, "text_qa", text_attempts)

    set_status(project_id, "visual_qa")
    visual_report = await visual_qa.audit_files(files, project_id, config, uploaded_images)
    visual_issues = list(visual_report.get("issues") or [])
    combined = text_issues + visual_issues

    while _severe(visual_issues) and visual_attempts < VISUAL_REPAIR_ATTEMPTS:
        repairable = _model_repairable(combined)
        if not repairable:
            break
        visual_attempts += 1
        set_status(project_id, "fixing")
        _record_interim_quality(project_id, combined, "visual_fixing", visual_attempts)
        files = await core.fix_files(files, repairable, config)
        set_status(project_id, "auditing")
        _strip_unsupported_contact_facts(files, config)
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        text_issues = audit1["issues"] + audit2.get("issues", [])
        set_status(project_id, "visual_qa")
        visual_report = await visual_qa.audit_files(files, project_id, config, uploaded_images)
        visual_issues = list(visual_report.get("issues") or [])
        combined = text_issues + visual_issues

    return files, combined, text_attempts + visual_attempts, visual_report


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
                        extra={"publish_action_required": "github_pages_permission", "payment_required": False, "originality": audit.get("originality") or {}},
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
                    extra={"payment_required": False, "payment_stage": "completed", "originality": audit.get("originality") or {}},
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
        if _cancel_checkpoint(project_id, "preparing"):
            return
        bypass = _sandbox_payment_bypass(str(row["user_id"]))
        stripe_required = billing.package_is_configured(config.get("package", "")) and not bypass

        # Payment/webhook resume path: if the site was already generated and held
        # for payment, never regenerate it. Publish the exact approved repository.
        if row["repo_name"] and audit.get("repository_ready") and not audit.get("public_live"):
            existing_issues = list(audit.get("issues") or [])
            existing_visual = dict(audit.get("visual_qa") or {})
            if _quality_gate_passed(existing_issues, existing_visual):
                if stripe_required and not billing.project_is_paid(project_id):
                    set_status(project_id, "ready_for_payment")
                    return
                await _publish_existing_project(project_id, row, audit)
                return
            # Existing repository did not pass the release gate. Continue into a
            # fresh self-heal/build cycle instead of exposing payment/publication.
            set_status(project_id, "needs_review")

        uploaded_images = _inject_uploaded_image_metadata(project_id, config)

        phase = "structure"
        if _cancel_checkpoint(project_id, "before_structure"):
            return
        set_status(project_id, "designing")
        spec = await core.design_site(config)

        phase = "website build"
        if _cancel_checkpoint(project_id, "before_build"):
            return
        set_status(project_id, "building")
        files = await core.build_files(config, spec)

        phase = "quality and visual review"
        if _cancel_checkpoint(project_id, "before_quality"):
            return
        set_status(project_id, "auditing")
        files, issues, attempts, visual_report = await _quality_cycle(files, config, project_id, uploaded_images)
        final_originality_issues, originality_report = originality_v2._originality_issues(files, config)
        known = {(str(i.get("code") or ""), str(i.get("file") or ""), str(i.get("message") or "")) for i in issues}
        for item in final_originality_issues:
            key = (str(item.get("code") or ""), str(item.get("file") or ""), str(item.get("message") or ""))
            if key not in known:
                issues.append(item)
                known.add(key)

        if _cancel_checkpoint(project_id, "before_delivery"):
            return
        _attach_uploaded_image_bytes(files, uploaded_images)
        _attach_delivery_manifest(
            files,
            project_id=project_id,
            config=config,
            visual_report=visual_report,
            originality=originality_report,
        )

        benchmark_mode = bool(config.get("_benchmark_mode"))
        if benchmark_mode:
            passed = _quality_gate_passed(issues, visual_report)
            benchmark_audit = _audit_payload(
                issues,
                visual_report,
                repository_ready=False,
                public_url=None,
                public_live=False,
                uploaded_images=len(uploaded_images),
                extra={
                    "benchmark_mode": True,
                    "quality_gate_passed": passed,
                    "payment_required": False,
                    "payment_stage": "benchmark",
                    "preview_ready": False,
                    "originality": originality_report,
                    "delivery_manifest": {
                        "file_count": len(files),
                        "sha256": hashlib.sha256(
                            json.dumps(
                                _delivery_manifest(
                                    files,
                                    project_id=project_id,
                                    config=config,
                                    visual_report=visual_report,
                                    originality=originality_report,
                                ),
                                sort_keys=True,
                            ).encode("utf-8")
                        ).hexdigest(),
                    },
                },
            )
            with core.db() as con:
                con.execute(
                    "UPDATE projects SET status=?,repo_name=NULL,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                    (
                        "ready" if passed else "needs_review",
                        benchmark_audit,
                        attempts,
                        core.now_iso(),
                        project_id,
                    ),
                )
            return

        repo_name = repo_name_for(config, project_id)

        # Store the finished source in GitHub first, but do NOT enable Pages yet.
        phase = "repository delivery"
        set_status(project_id, "repository_ready")
        if hasattr(core, "github_replace_bundle"):
            await core.github_replace_bundle(repo_name, files, f"Agent build for {config['name']}")
        else:
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
                "payment_stage": (
                    "after_build"
                    if stripe_required and _quality_gate_passed(issues, visual_report)
                    else "blocked_by_quality"
                    if stripe_required
                    else "not_required"
                ),
                "payment_blocked": not _quality_gate_passed(issues, visual_report),
                "quality_gate_passed": _quality_gate_passed(issues, visual_report),
                "preview_ready": True,
                "originality": originality_report,
            },
        )
        with core.db() as con:
            con.execute(
                "UPDATE projects SET repo_name=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (repo_name, audit_json, attempts, core.now_iso(), project_id),
            )

        if not _quality_gate_passed(issues, visual_report):
            set_status(project_id, "needs_review")
            logger.warning(
                "Website held by quality gate project=%s repo=%s visual_score=%s severe=%s",
                project_id,
                repo_name,
                visual_report.get("score"),
                _severe(issues),
            )
            return

        if stripe_required and not billing.project_is_paid(project_id):
            set_status(project_id, "ready_for_payment")
            logger.info("Website generated, quality-approved and held for payment project=%s repo=%s", project_id, repo_name)
            return

        # Development mode and the dedicated sandbox QA account publish without
        # charging. Production users reach this point only after payment.
        if _cancel_checkpoint(project_id, "before_publish"):
            return
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
