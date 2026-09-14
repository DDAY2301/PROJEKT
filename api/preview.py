"""Authenticated, short-lived previews for generated customer websites.

Generated repositories remain private until payment. This module creates a
short-lived signed preview URL that proxies the private repository through the
Project Visibility API, so customers can inspect the exact generated website
before paying without making GitHub Pages public.
"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import api.main as core

PREVIEW_TTL_MINUTES = 30


def _safe_path(value: str) -> str:
    raw = (value or "index.html").strip().lstrip("/") or "index.html"
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(400, "Invalid preview path")
    return str(path)


def _preview_token(project_id: str, user_id: str, repo_name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=PREVIEW_TTL_MINUTES)
    return jwt.encode(
        {
            "kind": "project_preview",
            "project_id": project_id,
            "user_id": user_id,
            "repo_name": repo_name,
            "exp": exp,
        },
        core.APP_SECRET,
        algorithm="HS256",
    )


def _decode_preview_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, core.APP_SECRET, algorithms=["HS256"])
    except Exception as exc:
        raise HTTPException(401, "Preview link is invalid or expired") from exc
    if payload.get("kind") != "project_preview":
        raise HTTPException(401, "Invalid preview token")
    return payload


@core.app.post("/projects/{project_id}/preview-session")
async def create_preview_session(
    project_id: str,
    request: Request,
    user_id: str = Depends(core.current_user),
):
    with core.db() as con:
        row = con.execute(
            "SELECT id,user_id,repo_name,last_audit_json,status FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    if not row["repo_name"]:
        raise HTTPException(409, "Preview becomes available after the generated source is ready")

    token = _preview_token(project_id, user_id, str(row["repo_name"]))
    base = str(request.base_url).rstrip("/")
    return {
        "project_id": project_id,
        "url": f"{base}/preview/{token}/index.html",
        "expires_in": PREVIEW_TTL_MINUTES * 60,
        "status": row["status"],
    }


@core.app.get("/preview/{token}", include_in_schema=False)
async def preview_root(token: str):
    _decode_preview_token(token)
    return RedirectResponse(url=f"/preview/{token}/index.html", status_code=307)


@core.app.get("/preview/{token}/{asset_path:path}", include_in_schema=False)
async def preview_asset(token: str, asset_path: str):
    payload = _decode_preview_token(token)
    project_id = str(payload.get("project_id") or "")
    repo_name = str(payload.get("repo_name") or "")
    user_id = str(payload.get("user_id") or "")
    if not project_id or not repo_name or not user_id:
        raise HTTPException(401, "Invalid preview token")

    with core.db() as con:
        row = con.execute(
            "SELECT repo_name FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not row or str(row["repo_name"] or "") != repo_name:
        raise HTTPException(404, "Preview project is no longer available")

    path = _safe_path(asset_path)
    headers = dict(core.github_headers())
    headers["Accept"] = "application/vnd.github.raw+json"
    url = f"https://api.github.com/repos/{core.GITHUB_OWNER}/{repo_name}/contents/{path}"
    async with httpx.AsyncClient(timeout=45, headers=headers, follow_redirects=True) as client:
        response = await client.get(url, params={"ref": "main"})
    if response.status_code == 404:
        raise HTTPException(404, "Preview file not found")
    if response.status_code >= 400:
        raise HTTPException(502, "Could not load preview file from GitHub")

    content = response.content
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if media_type == "text/html":
        try:
            text = content.decode("utf-8")
            # Keep all relative navigation and assets inside the signed preview
            # namespace, including pages such as about.html and assets/site.css.
            base_tag = f'<base href="/preview/{token}/">'
            if "<head" in text.lower() and "<base " not in text.lower():
                marker = text.lower().find(">", text.lower().find("<head"))
                if marker >= 0:
                    text = text[: marker + 1] + base_tag + text[marker + 1 :]
            content = text.encode("utf-8")
        except UnicodeDecodeError:
            pass

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Content-Security-Policy": "frame-ancestors *",
        },
    )
