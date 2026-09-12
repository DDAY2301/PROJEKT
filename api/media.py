"""Authenticated image uploads and responsive media processing.

Customer uploads are validated as real images, EXIF orientation is normalized,
and responsive WebP variants are generated before the build starts. AVIF is
created when the installed Pillow build supports it. The original upload is not
published automatically; generated variants are the delivery assets.
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

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
PHOTO_WIDTHS = (480, 960, 1440, 1920)
LOGO_WIDTHS = (160, 320, 640, 960)


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
        columns = {row["name"] for row in con.execute("PRAGMA table_info(project_images)").fetchall()}
        migrations = {
            "variants_json": "ALTER TABLE project_images ADD COLUMN variants_json TEXT NOT NULL DEFAULT '[]'",
            "width": "ALTER TABLE project_images ADD COLUMN width INTEGER NOT NULL DEFAULT 0",
            "height": "ALTER TABLE project_images ADD COLUMN height INTEGER NOT NULL DEFAULT 0",
            "focal_x": "ALTER TABLE project_images ADD COLUMN focal_x REAL NOT NULL DEFAULT 50",
            "focal_y": "ALTER TABLE project_images ADD COLUMN focal_y REAL NOT NULL DEFAULT 50",
            "kind": "ALTER TABLE project_images ADD COLUMN kind TEXT NOT NULL DEFAULT 'image'",
        }
        for name, sql in migrations.items():
            if name not in columns:
                con.execute(sql)


def images_for_project(project_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    ensure_media_schema()
    sql = "SELECT * FROM project_images WHERE project_id=?"
    params: tuple[Any, ...] = (project_id,)
    if user_id:
        sql += " AND user_id=?"
        params = (project_id, user_id)
    sql += " ORDER BY sort_order ASC, created_at ASC"
    with core.db() as con:
        rows = con.execute(sql, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["variants"] = json.loads(item.get("variants_json") or "[]")
        except Exception:
            item["variants"] = []
        result.append(item)
    return result


def _safe_stem(name: str) -> str:
    stem = Path(name or "image").stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return (stem or "image")[:48]


def _safe_placement(value: str) -> str:
    """Allow generic placement, logo, or an explicit page+role target."""
    value = (value or "auto").strip().lower()
    if value in {"auto", "hero", "gallery", "content", "logo"}:
        return value
    if re.fullmatch(r"page:[a-z0-9][a-z0-9-]{0,70}:(?:hero|gallery|content)", value):
        return value
    return "auto"


def _clamp_percent(value: float | int | str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 50.0
    return max(0.0, min(100.0, number))


def _normalise_kind(value: str, placement: str) -> str:
    raw = (value or "image").strip().lower()
    if placement == "logo" or raw == "logo":
        return "logo"
    return "image"


def _public_variant(variant: dict[str, Any]) -> dict[str, Any]:
    return {k: variant[k] for k in ("format", "width", "height", "repo_path") if k in variant}


def _prepare_source(data: bytes) -> Image.Image:
    try:
        opened = Image.open(io.BytesIO(data))
        opened.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(415, "The uploaded file is not a valid supported image") from exc
    image = ImageOps.exif_transpose(opened)
    # Keep alpha for logos/PNGs; normalise unusual colour spaces so WebP/AVIF
    # encoders behave consistently across Windows and Linux.
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image


def _save_variant(image: Image.Image, path: Path, fmt: str, *, logo: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if fmt == "WEBP":
            if logo:
                image.save(path, format="WEBP", lossless=True, method=6)
            else:
                image.save(path, format="WEBP", quality=84, method=6)
        elif fmt == "AVIF":
            image.save(path, format="AVIF", quality=58 if not logo else 72)
        else:
            return False
        return True
    except (OSError, ValueError, KeyError):
        return False


def _generate_variants(image: Image.Image, project_dir: Path, base: str, *, logo: bool) -> list[dict[str, Any]]:
    original_w, original_h = image.size
    widths = LOGO_WIDTHS if logo else PHOTO_WIDTHS
    target_widths = [w for w in widths if w <= original_w]
    if not target_widths or target_widths[-1] != original_w:
        target_widths.append(min(original_w, widths[-1]))
    target_widths = sorted(set(max(1, w) for w in target_widths))

    variants: list[dict[str, Any]] = []
    for width in target_widths:
        if width == original_w:
            resized = image.copy()
        else:
            height = max(1, round(original_h * width / original_w))
            resized = image.resize((width, height), Image.Resampling.LANCZOS)
        height = resized.height

        webp_name = f"{base}-w{width}.webp"
        webp_path = project_dir / webp_name
        if _save_variant(resized, webp_path, "WEBP", logo=logo):
            variants.append({
                "format": "webp",
                "width": width,
                "height": height,
                "repo_path": f"assets/images/{webp_name}",
                "stored_path": str(webp_path),
            })

        avif_name = f"{base}-w{width}.avif"
        avif_path = project_dir / avif_name
        if _save_variant(resized, avif_path, "AVIF", logo=logo):
            variants.append({
                "format": "avif",
                "width": width,
                "height": height,
                "repo_path": f"assets/images/{avif_name}",
                "stored_path": str(avif_path),
            })
        resized.close()

    if not variants:
        raise HTTPException(500, "Image optimisation could not create a browser-compatible variant")
    return variants


@core.app.post("/projects/{project_id}/images")
async def upload_project_image(
    project_id: str,
    file: UploadFile = File(...),
    alt_text: str = Form(default=""),
    placement: str = Form(default="auto"),
    focal_x: float = Form(default=50),
    focal_y: float = Form(default=50),
    kind: str = Form(default="image"),
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
        raise HTTPException(415, "Only JPG, PNG and WebP uploads are supported")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(400, "Image file is empty")

    placement = _safe_placement(placement)
    kind = _normalise_kind(kind, placement)
    if kind == "logo":
        placement = "logo"
    focal_x = _clamp_percent(focal_x)
    focal_y = _clamp_percent(focal_y)

    image = _prepare_source(data)
    original_w, original_h = image.size
    if original_w < 32 or original_h < 32:
        image.close()
        raise HTTPException(415, "Image dimensions are too small")
    if original_w * original_h > 50_000_000:
        image.close()
        raise HTTPException(413, "Image dimensions are too large")

    image_id = str(uuid.uuid4())
    base = f"{count + 1:02d}-{_safe_stem(file.filename or 'image')}-{image_id[:8]}"
    project_dir = UPLOAD_ROOT / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    variants = _generate_variants(image, project_dir, base, logo=kind == "logo")
    image.close()

    webp_variants = [v for v in variants if v["format"] == "webp"]
    primary = max(webp_variants or variants, key=lambda v: int(v["width"]))
    stored_path = primary["stored_path"]
    repo_path = primary["repo_path"]

    with core.db() as con:
        con.execute(
            """
            INSERT INTO project_images(
              id,project_id,user_id,original_name,stored_path,repo_path,mime_type,
              alt_text,placement,sort_order,created_at,variants_json,width,height,
              focal_x,focal_y,kind
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                image_id,
                project_id,
                user_id,
                file.filename or Path(repo_path).name,
                stored_path,
                repo_path,
                "image/webp",
                alt_text.strip()[:180],
                placement,
                count,
                core.now_iso(),
                json.dumps(variants, ensure_ascii=False),
                original_w,
                original_h,
                focal_x,
                focal_y,
                kind,
            ),
        )
    return {
        "id": image_id,
        "name": file.filename or Path(repo_path).name,
        "repo_path": repo_path,
        "alt_text": alt_text.strip()[:180],
        "placement": placement,
        "kind": kind,
        "focal_x": focal_x,
        "focal_y": focal_y,
        "width": original_w,
        "height": original_h,
        "variants": [_public_variant(v) for v in variants],
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
            "kind": row.get("kind") or "image",
            "focal_x": float(row.get("focal_x") or 50),
            "focal_y": float(row.get("focal_y") or 50),
            "width": int(row.get("width") or 0),
            "height": int(row.get("height") or 0),
            "variants": [_public_variant(v) for v in (row.get("variants") or [])],
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
    paths: set[str] = {str(row["stored_path"] or "")}
    try:
        for variant in json.loads(row["variants_json"] or "[]"):
            if variant.get("stored_path"):
                paths.add(str(variant["stored_path"]))
    except Exception:
        pass
    for path in paths:
        if not path:
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted": True, "id": image_id}
