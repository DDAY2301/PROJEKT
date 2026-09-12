"""Authenticated image uploads for generated websites."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile

import api.main as core

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "api/data/uploads"))
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
MAX_IMAGES_PER_PROJECT = int(os.getenv("MAX_IMAGES_PER_PROJECT", "12"))
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def ensure_media_schema() -> None:
    with core.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_images (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              original_name TEXT NOT NULL,
              stored_path TEXT NOT NULL,
              repo_path TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              alt_text TEXT NOT NULL DEFAULT '',
              placement TEXT NOT NULL DEFAULT 'auto',
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id),
              FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )


def images_for_project(project_id: str, user_id: str | None = None) -> list[dict]:
    ensure_media_schema()
    sql = "SELECT * FROM project_images WHERE project_id=?"
    params: tuple = (project_id,)
    if user_id:
        sql += " AND user_id=?"
        params = (project_id, user_id)
    sql += " ORDER BY sort_order ASC, created_at ASC"
    with core.db() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _safe_stem(name: str) -> str:
    stem = Path(name or "image").stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return (stem or "image")[:48]


def _safe_placement(value: str) -> str:
    """Allow generic placement or an explicit page+role target.

    Examples:
      hero
      gallery
      content
      auto
      page:index:hero
      page:programme:content
      page:stories:gallery
    """
    value = (value or "auto").strip().lower()
    if value in {"auto", "hero", "gallery", "content"}:
        return value
    if re.fullmatch(r"page:[a-z0-9][a-z0-9-]{0,70}:(?:hero|gallery|content)", value):
        return value
    return "auto"


@core.app.post("/projects/{project_id}/images")
async def upload_project_image(
    project_id: str,
    file: UploadFile = File(...),
    alt_text: str = Form(default=""),
    placement: str = Form(default="auto"),
    user_id: str = Depends(core.current_user),
):
    ensure_media_schema()
    with core.db() as con:
        project = con.execute(
            "SELECT id FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        count = con.execute(
            "SELECT COUNT(*) AS n FROM project_images WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()["n"]
    if not project:
        raise HTTPException(404, "Project not found")
    if count >= MAX_IMAGES_PER_PROJECT:
        raise HTTPException(409, f"A project can contain at most {MAX_IMAGES_PER_PROJECT} uploaded images")

    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_TYPES:
        raise HTTPException(415, "Only JPG, PNG and WebP images are supported")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(400, "Image file is empty")

    placement = _safe_placement(placement)
    image_id = str(uuid.uuid4())
    ext = ALLOWED_TYPES[mime]
    filename = f"{count + 1:02d}-{_safe_stem(file.filename or 'image')}-{image_id[:8]}{ext}"
    project_dir = UPLOAD_ROOT / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    stored = project_dir / filename
    stored.write_bytes(data)
    repo_path = f"assets/images/{filename}"

    with core.db() as con:
        con.execute(
            """
            INSERT INTO project_images(
              id,project_id,user_id,original_name,stored_path,repo_path,mime_type,
              alt_text,placement,sort_order,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                image_id,
                project_id,
                user_id,
                file.filename or filename,
                str(stored),
                repo_path,
                mime,
                alt_text.strip()[:180],
                placement,
                count,
                core.now_iso(),
            ),
        )
    return {
        "id": image_id,
        "name": file.filename or filename,
        "repo_path": repo_path,
        "alt_text": alt_text.strip()[:180],
        "placement": placement,
    }


@core.app.get("/projects/{project_id}/images")
async def list_project_images(project_id: str, user_id: str = Depends(core.current_user)):
    with core.db() as con:
        project = con.execute(
            "SELECT id FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    return [
        {
            "id": row["id"],
            "name": row["original_name"],
            "repo_path": row["repo_path"],
            "alt_text": row["alt_text"],
            "placement": row["placement"],
        }
        for row in images_for_project(project_id, user_id)
    ]


@core.app.delete("/projects/{project_id}/images/{image_id}")
async def delete_project_image(project_id: str, image_id: str, user_id: str = Depends(core.current_user)):
    ensure_media_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT * FROM project_images WHERE id=? AND project_id=? AND user_id=?",
            (image_id, project_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Image not found")
        con.execute("DELETE FROM project_images WHERE id=?", (image_id,))
    try:
        Path(row["stored_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"deleted": True, "id": image_id}
