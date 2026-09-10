"""Natural-language revision engine for already generated customer websites.

The first build creates a complete static site. This module lets the owner ask
for a focused follow-up change in plain language. The agent reads the current
GitHub source, changes only the necessary files, runs the same QA/self-fix
pipeline and republishes the site.
"""

import asyncio
import base64
import json
import re
import uuid

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import api.main as core
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


def _safe_text_path(path: str) -> bool:
    if not path or path.startswith(".") or ".." in path.split("/"):
        return False
    lower = path.lower()
    return lower.endswith((".html", ".css", ".js", ".json", ".xml", ".txt", ".md", ".svg"))


async def github_get_text_bundle(repo_name: str) -> dict[str, str]:
    """Load the current editable text source from the generated repository."""
    headers = core.github_headers()
    api = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        tree = await client.get(f"{api}/git/trees/main", params={"recursive": "1"})
        if tree.status_code >= 400:
            raise RuntimeError(f"Could not read generated repository tree: {tree.text[:300]}")
        tree_data = tree.json()
        if tree_data.get("truncated"):
            raise RuntimeError("Generated repository is too large for safe automatic revision")

        candidates = [
            item for item in tree_data.get("tree", [])
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
            # Keep the local model inside a predictable context budget. Normal
            # generated sites are well below this threshold.
            if total_chars + len(content) > 80_000:
                continue
            files[item["path"]] = content
            total_chars += len(content)

    if "index.html" not in files:
        raise RuntimeError("Generated repository does not contain an editable index.html")
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


async def run_revision(project_id: str, revision_id: str, instruction: str) -> None:
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
        with core.db() as con:
            con.execute("UPDATE projects SET status='revising',updated_at=? WHERE id=?", (core.now_iso(), project_id))

        files = await github_get_text_bundle(repo_name)
        files, summary = await revise_files(files, instruction, config)

        _set_revision_status(revision_id, "auditing")
        with core.db() as con:
            con.execute("UPDATE projects SET status='auditing',updated_at=? WHERE id=?", (core.now_iso(), project_id))
        audit1 = core.static_audit(files)
        audit2 = await core.ai_audit(files, config)
        issues = audit1["issues"] + audit2.get("issues", [])

        attempts = 0
        while any(i.get("severity") in {"critical", "high"} for i in issues) and attempts < core.MAX_AUTO_FIX_ATTEMPTS:
            attempts += 1
            _set_revision_status(revision_id, "fixing")
            with core.db() as con:
                con.execute("UPDATE projects SET status='fixing',updated_at=? WHERE id=?", (core.now_iso(), project_id))
            files = await core.fix_files(files, issues, config)
            audit1 = core.static_audit(files)
            audit2 = await core.ai_audit(files, config)
            issues = audit1["issues"] + audit2.get("issues", [])

        _set_revision_status(revision_id, "publishing")
        with core.db() as con:
            con.execute("UPDATE projects SET status='publishing',updated_at=? WHERE id=?", (core.now_iso(), project_id))
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

        final_status = "ready" if not any(i.get("severity") in {"critical", "high"} for i in issues) else "needs_review"
        _set_revision_status(revision_id, final_status)
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status=?,last_audit_json=?,auto_fix_attempts=?,updated_at=? WHERE id=?",
                (
                    final_status,
                    json.dumps({"issues": issues, "revision_summary": summary}, ensure_ascii=False),
                    attempts,
                    core.now_iso(),
                    project_id,
                ),
            )
    except Exception as exc:
        _set_revision_status(revision_id, "failed")
        failure = {
            "issues": [{
                "severity": "critical",
                "code": "REVISION_FAILED",
                "file": "",
                "message": str(exc)[:700],
            }]
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
        if row["status"] in {"designing", "building", "auditing", "fixing", "publishing", "revising"}:
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
