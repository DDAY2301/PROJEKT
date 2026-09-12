"""Natural-language revision engine for already generated customer websites.

A revision is treated with the same production standard as the first build:
read the current GitHub source, change only what the owner requested, run text
and premium QA, render every page at desktop/tablet/mobile, repair severe
render regressions, publish, and verify the live URL.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import api.main as core
import api.visual_qa as visual_qa
from api.pages_publish import publish_generated_site, wait_for_generated_site


class RevisionIn(BaseModel):
    instruction: str = Field(min_length=3, max_length=3000)


def _ensure_revision_table() -> None:
    with core.db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS revisions (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              instruction TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id)
            )
            """
        )


def _set_revision_status(revision_id: str, status: str) -> None:
    with core.db() as con:
        con.execute(
            "UPDATE revisions SET status=?,updated_at=? WHERE id=?",
            (status, core.now_iso(), revision_id),
        )


def _set_project_status(project_id: str, status: str) -> None:
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,updated_at=? WHERE id=?",
            (status, core.now_iso(), project_id),
        )


def _safe_text_path(path: str) -> bool:
    if not path or path.startswith(".") or ".." in path.split("/"):
        return False
    return path.lower().endswith((".html", ".css", ".js", ".json", ".xml", ".txt", ".md", ".svg"))


def _safe_media_path(path: str) -> bool:
    low = path.lower()
    return path.startswith("assets/images/") and low.endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")) and ".." not in path.split("/")


async def _repo_tree(client: httpx.AsyncClient, repo_name: str) -> list[dict[str, Any]]:
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    tree = await client.get(f"{api}/git/trees/main", params={"recursive": "1"})
    if tree.status_code >= 400:
        raise RuntimeError(f"Could not read generated repository tree: {tree.text[:300]}")
    data = tree.json()
    if data.get("truncated"):
        raise RuntimeError("Generated repository is too large for safe automatic revision")
    return list(data.get("tree") or [])


async def github_get_text_bundle(repo_name: str) -> dict[str, str]:
    """Load the current editable text source from the generated repository."""
    headers = core.github_headers()
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        tree_data = await _repo_tree(client, repo_name)
        candidates = [
            item for item in tree_data
            if item.get("type") == "blob"
            and int(item.get("size") or 0) <= 180_000
            and _safe_text_path(str(item.get("path") or ""))
        ][:60]
        files: dict[str, str] = {}
        total_chars = 0
        for item in candidates:
            blob = await client.get(f"{api}/git/blobs/{item['sha']}")
            if blob.status_code >= 400:
                continue
            data = blob.json()
            if data.get("encoding") != "base64":
                continue
            try:
                content = base64.b64decode(data.get("content", "")).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
            if total_chars + len(content) > 80_000:
                continue
            files[item["path"]] = content
            total_chars += len(content)
    if "index.html" not in files:
        raise RuntimeError("Generated repository does not contain an editable index.html")
    return files


async def github_get_media_bundle(repo_name: str) -> dict[str, bytes]:
    """Fetch a bounded set of existing delivered image assets for visual QA.

    Revisions must render the real published media even when the original local
    upload folder is no longer present. Binary assets are never sent to Ollama.
    """
    headers = core.github_headers()
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    async with httpx.AsyncClient(timeout=90, headers=headers) as client:
        tree_data = await _repo_tree(client, repo_name)
        candidates = [
            item for item in tree_data
            if item.get("type") == "blob"
            and _safe_media_path(str(item.get("path") or ""))
            and int(item.get("size") or 0) <= 8 * 1024 * 1024
        ][:80]
        files: dict[str, bytes] = {}
        total = 0
        for item in candidates:
            size = int(item.get("size") or 0)
            if total + size > 45 * 1024 * 1024:
                break
            blob = await client.get(f"{api}/git/blobs/{item['sha']}")
            if blob.status_code >= 400:
                continue
            data = blob.json()
            if data.get("encoding") != "base64":
                continue
            try:
                raw = base64.b64decode(data.get("content", ""))
            except ValueError:
                continue
            files[str(item["path"])] = raw
            total += len(raw)
    return files


async def revise_files(files: dict[str, str], instruction: str, config: dict) -> tuple[dict[str, str], str]:
    system = (
        "You are a senior web designer and frontend engineer editing an existing production website. "
        "Return strict JSON only. Preserve everything the customer did not ask to change."
    )
    prompt = f"""
Apply this customer revision to the EXISTING website:
REVISION={json.dumps(instruction, ensure_ascii=False)}
PROJECT={json.dumps(config, ensure_ascii=False)}
CURRENT_FILES={json.dumps(files, ensure_ascii=False)}

Return strict JSON in this shape:
{{"changed_files":{{"path":"COMPLETE replacement file content"}},"summary":"short description"}}

Rules:
- return ONLY files that actually need changing
- each returned value must be the COMPLETE replacement content for that file
- preserve existing navigation, responsive behavior, accessibility and visual identity unless the instruction changes them
- do not remove working content unrelated to the request
- no external trackers, credentials, remote-execution code or secrets
- never return markdown fences
"""
    raw = core.strip_fence(await core.ollama(prompt, system))
    try:
        data = json.loads(raw)
        changed = data.get("changed_files") or {}
        if not isinstance(changed, dict) or not changed:
            raise ValueError("no changed files")
        merged = dict(files)
        for path, content in changed.items():
            path = str(path)
            if not _safe_text_path(path):
                raise ValueError(f"unsafe revision path: {path}")
            merged[path] = str(content)
        if "index.html" not in merged or "assets/site.css" not in merged:
            raise ValueError("required site files missing after revision")
        return merged, str(data.get("summary") or "Sprememba pripravljena")[:500]
    except Exception as exc:
        raise RuntimeError(f"Model did not return a valid revision patch: {exc}") from exc


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


async def _quality_cycle(
    files: dict[str, str],
    media_files: dict[str, bytes],
    config: dict[str, Any],
    project_id: str,
    revision_id: str,
) -> tuple[dict[str, str], list[dict[str, Any]], int, dict[str, Any]]:
    attempts = 0
    audit1 = core.static_audit(files)
    audit2 = await core.ai_audit(files, config)
    text_issues = audit1["issues"] + audit2.get("issues", [])
    while _severe(text_issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
        attempts += 1
        _set_revision_status(revision_id, "fixing")
        _set_project_status(project_id, "fixing")
        files = await core.fix_files(files, text_issues, config)
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        text_issues = audit1["issues"] + audit2.get("issues", [])

    _set_revision_status(revision_id, "visual_qa")
    _set_project_status(project_id, "visual_qa")
    visual_report = await visual_qa.audit_files(
        {**files, **media_files},
        f"{project_id}-rev-{revision_id[:8]}",
        config,
        [],
    )
    visual_issues = list(visual_report.get("issues") or [])
    combined = text_issues + visual_issues
    while _severe(visual_issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
        attempts += 1
        _set_revision_status(revision_id, "fixing")
        _set_project_status(project_id, "fixing")
        files = await core.fix_files(files, combined, config)
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        text_issues = audit1["issues"] + audit2.get("issues", [])
        _set_revision_status(revision_id, "visual_qa")
        _set_project_status(project_id, "visual_qa")
        visual_report = await visual_qa.audit_files(
            {**files, **media_files},
            f"{project_id}-rev-{revision_id[:8]}",
            config,
            [],
        )
        visual_issues = list(visual_report.get("issues") or [])
        combined = text_issues + visual_issues
    return files, combined, attempts, visual_report


async def run_revision(project_id: str, revision_id: str, instruction: str) -> None:
    visual_report: dict[str, Any] = {"available": False, "passed": False}
    try:
        with core.db() as con:
            row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise RuntimeError("Project not found")
            if not row["repo_name"]:
                raise RuntimeError("Initial website build must finish before requesting a revision")
            config = json.loads(row["config_json"])
            repo_name = row["repo_name"]

        _set_revision_status(revision_id, "revising")
        _set_project_status(project_id, "revising")
        files = await github_get_text_bundle(repo_name)
        media_files = await github_get_media_bundle(repo_name)
        files, summary = await revise_files(files, instruction, config)

        _set_revision_status(revision_id, "auditing")
        _set_project_status(project_id, "auditing")
        files, issues, attempts, visual_report = await _quality_cycle(
            files, media_files, config, project_id, revision_id
        )

        _set_revision_status(revision_id, "publishing")
        _set_project_status(project_id, "publishing")
        await core.github_put_bundle(repo_name, files, f"Website revision: {instruction[:90]}")
        public_url = await publish_generated_site(repo_name)
        live = await wait_for_generated_site(public_url, seconds=75)
        if not live:
            issues.append({
                "severity": "low",
                "code": "PAGES_PROPAGATING",
                "file": "",
                "message": "GitHub Pages deployment is still propagating; source was published successfully.",
            })

        final_status = "ready" if not _severe(issues) else "needs_review"
        _set_revision_status(revision_id, final_status)
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (
                    final_status,
                    json.dumps({
                        "issues": issues,
                        "revision_summary": summary,
                        "repository_ready": True,
                        "public_url": public_url,
                        "public_live": live,
                        "visual_qa": _visual_summary(visual_report),
                    }, ensure_ascii=False),
                    attempts,
                    core.now_iso(),
                    project_id,
                ),
            )
    except Exception as exc:
        _set_revision_status(revision_id, "failed")
        failure = {
            "visual_qa": _visual_summary(visual_report),
            "issues": [{
                "severity": "critical",
                "code": "REVISION_FAILED",
                "file": "",
                "message": str(exc)[:700],
            }],
        }
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='failed',last_audit_json=?,updated_at=? WHERE id=?",
                (json.dumps(failure, ensure_ascii=False), core.now_iso(), project_id),
            )


@core.app.post("/projects/{project_id}/revise")
async def revise_project(project_id: str, data: RevisionIn, user_id: str = Depends(core.current_user)):
    _ensure_revision_table()
    instruction = data.instruction.strip()
    with core.db() as con:
        row = con.execute(
            "SELECT id,repo_name,status FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        if not row["repo_name"]:
            raise HTTPException(409, "Initial website build must finish before requesting a revision")
        if row["status"] in {"designing", "building", "auditing", "visual_qa", "fixing", "publishing", "revising"}:
            raise HTTPException(409, "A build or revision is already running")
        revision_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO revisions(id,project_id,instruction,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (revision_id, project_id, instruction, "queued", core.now_iso(), core.now_iso()),
        )
    asyncio.create_task(run_revision(project_id, revision_id, instruction))
    return {"id": revision_id, "project_id": project_id, "status": "queued"}


@core.app.get("/projects/{project_id}/revisions")
async def list_revisions(project_id: str, user_id: str = Depends(core.current_user)):
    _ensure_revision_table()
    with core.db() as con:
        owned = con.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if not owned:
            raise HTTPException(404, "Project not found")
        rows = con.execute(
            "SELECT id,instruction,status,created_at,updated_at FROM revisions WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]
