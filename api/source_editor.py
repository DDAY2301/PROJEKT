"""Authenticated source editor and Git-backed version control.

The customer can inspect and edit delivered text source without receiving
GitHub credentials. Every save becomes a normal GitHub commit. Rollback creates
a new commit that points at the selected historical tree, preserving history
instead of force-resetting the branch.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from pathlib import PurePosixPath
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

import api.main as core
import api.repo_map as repo_map
import api.revisions as revisions
from api.pages_publish import publish_generated_site, wait_for_generated_site

MAX_EDITOR_FILE_BYTES = 420_000
MAX_EDITOR_FILES = 140
TEXT_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json", ".xml", ".txt", ".md", ".svg", ".webmanifest"}
SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})"
)


class EditorFileIn(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=420_000)
    message: str = Field(default="Edit website source", max_length=140)


class RollbackIn(BaseModel):
    sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")


def _safe_path(path: str) -> str:
    path = str(PurePosixPath((path or "").strip().replace("\\", "/")))
    parts = path.split("/")
    if (
        not path
        or path.startswith("/")
        or path.startswith(".")
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(path).suffix.lower() not in TEXT_EXTENSIONS
    ):
        raise HTTPException(422, "This file path is not editable")
    return path


def _project(project_id: str, user_id: str) -> dict[str, Any]:
    with core.db() as con:
        row = con.execute(
            "SELECT id,name,repo_name,status,last_audit_json FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    data = dict(row)
    if not data.get("repo_name"):
        raise HTTPException(409, "Project source is not ready yet")
    return data


def _api(repo_name: str) -> str:
    return f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}"


async def _tree(client: httpx.AsyncClient, repo_name: str) -> list[dict[str, Any]]:
    response = await client.get(f"{_api(repo_name)}/git/trees/main", params={"recursive": "1"})
    if response.status_code >= 400:
        raise HTTPException(502, f"Could not read repository tree: {response.text[:220]}")
    data = response.json()
    if data.get("truncated"):
        raise HTTPException(409, "Repository is too large for the browser source editor")
    return list(data.get("tree") or [])


async def _head_sha(client: httpx.AsyncClient, repo_name: str) -> str:
    response = await client.get(f"{_api(repo_name)}/git/ref/heads/main")
    if response.status_code >= 400:
        raise HTTPException(502, "Could not read the current repository version")
    return str((response.json().get("object") or {}).get("sha") or "")


def _validate_content(path: str, content: str) -> list[str]:
    warnings: list[str] = []
    if SECRET_RE.search(content):
        raise HTTPException(422, "Possible credential or secret detected; public website source must not contain secrets")

    low = path.lower()
    if low.endswith((".html", ".htm")):
        lower = content.lower()
        if "<!doctype html" not in lower or "<main" not in lower or "</html>" not in lower:
            raise HTTPException(422, "HTML page must remain a complete document with doctype, main and closing html tag")
        if "<title" not in lower:
            warnings.append("Page has no title element.")
    elif low.endswith((".js", ".mjs", ".cjs")):
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=True) as handle:
                handle.write(content)
                handle.flush()
                check = subprocess.run(
                    ["node", "--check", handle.name],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            if check.returncode != 0:
                detail = (check.stderr or check.stdout or "JavaScript syntax error").strip()
                raise HTTPException(422, detail[:700])
        except FileNotFoundError:
            warnings.append("Node.js is not installed; JavaScript syntax check was skipped.")
        except subprocess.TimeoutExpired:
            warnings.append("JavaScript syntax check timed out and was skipped.")
    elif low.endswith(".json"):
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"Invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    return warnings


@core.app.get("/projects/{project_id}/editor/files")
async def editor_files(project_id: str, user_id: str = Depends(core.current_user)):
    project = _project(project_id, user_id)
    headers = core.github_headers()
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        items = await _tree(client, project["repo_name"])
        head = await _head_sha(client, project["repo_name"])
    files = []
    for item in items:
        path = str(item.get("path") or "")
        ext = PurePosixPath(path).suffix.lower()
        size = int(item.get("size") or 0)
        if item.get("type") != "blob" or ext not in TEXT_EXTENSIONS or size > MAX_EDITOR_FILE_BYTES:
            continue
        files.append({"path": path, "size": size, "sha": item.get("sha")})
        if len(files) >= MAX_EDITOR_FILES:
            break
    return {"project_id": project_id, "repo_name": project["repo_name"], "head": head, "files": files}


@core.app.get("/projects/{project_id}/editor/file")
async def editor_file(
    project_id: str,
    path: str = Query(min_length=1, max_length=240),
    user_id: str = Depends(core.current_user),
):
    project = _project(project_id, user_id)
    path = _safe_path(path)
    headers = core.github_headers()
    async with httpx.AsyncClient(timeout=45, headers=headers) as client:
        response = await client.get(f"{_api(project['repo_name'])}/contents/{path}", params={"ref": "main"})
    if response.status_code == 404:
        raise HTTPException(404, "File not found")
    if response.status_code >= 400:
        raise HTTPException(502, "Could not read the source file")
    data = response.json()
    if int(data.get("size") or 0) > MAX_EDITOR_FILE_BYTES:
        raise HTTPException(413, "File is too large for the browser editor")
    try:
        content = base64.b64decode(data.get("content") or "").decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(415, "File is not UTF-8 editable text") from exc
    return {"path": path, "sha": data.get("sha"), "content": content}


@core.app.put("/projects/{project_id}/editor/file")
async def save_editor_file(
    project_id: str,
    data: EditorFileIn,
    user_id: str = Depends(core.current_user),
):
    project = _project(project_id, user_id)
    path = _safe_path(data.path)
    content = data.content
    if len(content.encode("utf-8")) > MAX_EDITOR_FILE_BYTES:
        raise HTTPException(413, "File is too large for the browser editor")
    warnings = _validate_content(path, content)

    headers = core.github_headers()
    api = _api(project["repo_name"])
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        before = await _head_sha(client, project["repo_name"])
        existing = await client.get(f"{api}/contents/{path}", params={"ref": "main"})
        if existing.status_code not in {200, 404}:
            raise HTTPException(502, "Could not inspect the existing source file")
        payload: dict[str, Any] = {
            "message": (data.message.strip() or f"Edit {path}")[:140],
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": "main",
        }
        if existing.status_code == 200:
            payload["sha"] = existing.json().get("sha")
        saved = await client.put(f"{api}/contents/{path}", json=payload)
        if saved.status_code >= 400:
            raise HTTPException(502, f"Could not save source file: {saved.text[:260]}")
        after = str(((saved.json().get("commit") or {}).get("sha")) or "")

    with core.db() as con:
        con.execute(
            "UPDATE projects SET updated_at=? WHERE id=?",
            (core.now_iso(), project_id),
        )
    return {
        "saved": True,
        "path": path,
        "previous_version": before,
        "version": after,
        "warnings": warnings,
    }


@core.app.get("/projects/{project_id}/editor/context")
async def editor_context(project_id: str, user_id: str = Depends(core.current_user)):
    project = _project(project_id, user_id)
    files = await revisions.github_get_text_bundle(project["repo_name"])
    return {
        "project_id": project_id,
        "repo_map": repo_map.build_repo_map(files),
        "editable_files": len(files),
    }


@core.app.get("/projects/{project_id}/versions")
async def project_versions(project_id: str, user_id: str = Depends(core.current_user)):
    project = _project(project_id, user_id)
    headers = core.github_headers()
    async with httpx.AsyncClient(timeout=45, headers=headers) as client:
        response = await client.get(f"{_api(project['repo_name'])}/commits", params={"sha": "main", "per_page": 30})
    if response.status_code >= 400:
        raise HTTPException(502, "Could not load project versions")
    versions = []
    for item in response.json():
        commit = item.get("commit") or {}
        author = commit.get("author") or {}
        versions.append({
            "sha": item.get("sha"),
            "message": str(commit.get("message") or "").split("\n", 1)[0][:180],
            "date": author.get("date"),
            "author": author.get("name"),
        })
    return versions


@core.app.post("/projects/{project_id}/rollback")
async def rollback_project(
    project_id: str,
    data: RollbackIn,
    user_id: str = Depends(core.current_user),
):
    project = _project(project_id, user_id)
    target = data.sha.lower()
    headers = core.github_headers()
    api = _api(project["repo_name"])

    with core.db() as con:
        con.execute("UPDATE projects SET status='publishing',updated_at=? WHERE id=?", (core.now_iso(), project_id))

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        commits = await client.get(f"{api}/commits", params={"sha": "main", "per_page": 50})
        if commits.status_code >= 400:
            raise HTTPException(502, "Could not validate rollback version")
        allowed = {str(item.get("sha") or "").lower() for item in commits.json()}
        if target not in allowed:
            raise HTTPException(409, "Rollback target is not in the recent project history")

        current = await _head_sha(client, project["repo_name"])
        if current.lower() == target:
            return {"rolled_back": False, "version": current, "message": "Project is already on this version"}

        old_commit = await client.get(f"{api}/git/commits/{target}")
        if old_commit.status_code >= 400:
            raise HTTPException(502, "Could not read rollback commit")
        tree_sha = str((old_commit.json().get("tree") or {}).get("sha") or "")
        if not tree_sha:
            raise HTTPException(502, "Rollback commit has no source tree")

        created = await client.post(
            f"{api}/git/commits",
            json={
                "message": f"Rollback website to {target[:10]}",
                "tree": tree_sha,
                "parents": [current],
            },
        )
        if created.status_code >= 400:
            raise HTTPException(502, f"Could not create rollback commit: {created.text[:260]}")
        new_sha = str(created.json().get("sha") or "")

        updated = await client.patch(
            f"{api}/git/refs/heads/main",
            json={"sha": new_sha, "force": False},
        )
        if updated.status_code >= 400:
            raise HTTPException(502, f"Could not activate rollback commit: {updated.text[:260]}")

    public_url = await publish_generated_site(project["repo_name"])
    live = await wait_for_generated_site(public_url, seconds=75)

    try:
        audit = json.loads(project.get("last_audit_json") or "{}")
        if not isinstance(audit, dict):
            audit = {}
    except Exception:
        audit = {}
    audit.update({
        "repository_ready": True,
        "public_url": public_url,
        "public_live": live,
        "editor_last_action": {
            "type": "rollback",
            "target": target,
            "version": new_sha,
            "at": core.now_iso(),
        },
    })
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status=?,last_audit_json=?,updated_at=? WHERE id=?",
            ("ready" if live else "needs_review", json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
        )
    return {
        "rolled_back": True,
        "target": target,
        "version": new_sha,
        "public_url": public_url,
        "public_live": live,
    }
