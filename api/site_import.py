"""Safe ZIP import for existing static websites.

Users can drag an existing site archive into Project Visibility and immediately
bring it under the same private GitHub delivery, visual QA, revision and source
editor workflow as generated sites. Extraction is bounded and rejects traversal,
symlinks, executable/server-side code and archive-bomb style payloads.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import Depends, File, Form, HTTPException, UploadFile

import api.main as core
import api.visual_qa as visual_qa

MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 260

TEXT_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json", ".xml", ".txt", ".md", ".svg", ".webmanifest"}
BINARY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".ico", ".woff", ".woff2"}
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | BINARY_EXTENSIONS
IGNORED_ROOTS = {".git", ".github", "node_modules", "__macosx", ".idea", ".vscode"}


def _safe_name(value: str, fallback: str = "Imported website") -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    return (value or fallback)[:120]


def _normalise_member(name: str) -> str | None:
    raw = (name or "").replace("\\", "/").lstrip("/")
    if not raw or raw.endswith("/"):
        return None
    path = PurePosixPath(raw)
    parts = list(path.parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(422, "ZIP contains an unsafe path")
    if parts[0].lower() in IGNORED_ROOTS or any(part.lower() in IGNORED_ROOTS for part in parts):
        return None
    if any(part.startswith(".") for part in parts):
        return None
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    return "/".join(parts)


def _strip_common_root(files: dict[str, bytes]) -> dict[str, bytes]:
    if not files:
        return files
    parts = [path.split("/") for path in files]
    if all(len(p) > 1 for p in parts):
        root = parts[0][0]
        if all(p[0] == root for p in parts):
            return {"/".join(path.split("/")[1:]): data for path, data in files.items()}
    return files


def _title_from_html(content: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
    if not match:
        return fallback
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:100] or fallback


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


IMPORT_STAGE_ROOT = Path(core.DB_PATH).resolve().parent / "site-imports"
IMPORT_STAGE_ROOT.mkdir(parents=True, exist_ok=True)
_import_tasks: dict[str, asyncio.Task] = {}


def _stage_dir(project_id: str) -> Path:
    return IMPORT_STAGE_ROOT / project_id


def _write_stage(project_id: str, files: dict[str, bytes], manifest: dict[str, Any]) -> None:
    root = _stage_dir(project_id)
    if root.exists():
        import shutil
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        target = root.joinpath(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (root / ".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _read_stage(project_id: str) -> tuple[dict[str, bytes], dict[str, Any]]:
    root = _stage_dir(project_id)
    manifest_path = root / ".manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Import staging data is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path == manifest_path:
            continue
        rel = path.relative_to(root).as_posix()
        files[rel] = path.read_bytes()
    return files, manifest


def _stage_text_files(files: dict[str, bytes]) -> tuple[dict[str, str], dict[str, str | bytes]]:
    text_files: dict[str, str] = {}
    deliverable: dict[str, str | bytes] = {}
    for path, data in files.items():
        ext = PurePosixPath(path).suffix.lower()
        if ext in TEXT_EXTENSIONS:
            text = data.decode("utf-8")
            text_files[path] = text
            deliverable[path] = text
        else:
            deliverable[path] = data
    return text_files, deliverable


async def _process_staged_import(project_id: str) -> None:
    try:
        extracted, manifest = _read_stage(project_id)
        text_files, deliverable = _stage_text_files(extracted)
        config = manifest["config"]
        repo_slug = manifest["repo_slug"]
        safe_name = manifest["safe_name"]

        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='repository_ready',updated_at=? WHERE id=?",
                (core.now_iso(), project_id),
            )

        # Replace the repository as one atomic tree. Files absent from the ZIP
        # (including the auto-init README) disappear from the current version,
        # while the previous commit remains available for rollback.
        replacement = await core.github_replace_bundle(
            repo_slug,
            deliverable,
            f"Import existing website: {safe_name}",
        )

        static_report = core.static_audit(text_files)
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status='auditing',updated_at=? WHERE id=?",
                (core.now_iso(), project_id),
            )
        visual_report = await visual_qa.audit_files(deliverable, f"{project_id}-import", config, [])
        issues = list(static_report.get("issues") or []) + list(visual_report.get("issues") or [])
        severe = any(item.get("severity") in {"critical", "high"} for item in issues if isinstance(item, dict))
        audit = {
            "issues": issues,
            "repository_ready": True,
            "public_url": None,
            "public_live": False,
            "preview_ready": True,
            "imported_source": True,
            "imported_files": len(deliverable),
            "visual_qa": _visual_summary(visual_report),
            "source_commit": replacement.get("after"),
            "source_previous_commit": replacement.get("before"),
            "repository_replace_mode": "atomic_full_tree",
        }
        with core.db() as con:
            con.execute(
                "UPDATE projects SET status=?,last_audit_json=?,updated_at=? WHERE id=?",
                ("needs_review" if severe else "ready", json.dumps(audit, ensure_ascii=False), core.now_iso(), project_id),
            )
    except Exception as exc:
        with core.db() as con:
            row = con.execute("SELECT last_audit_json FROM projects WHERE id=?", (project_id,)).fetchone()
            previous = {}
            try:
                previous = json.loads(row["last_audit_json"] or "{}") if row else {}
            except Exception:
                previous = {}
            previous.update({
                "issues": [{
                    "severity": "critical",
                    "code": "ZIP_IMPORT_FAILED",
                    "file": "",
                    "message": str(exc)[:700],
                }],
                "imported_source": True,
                "import_failed": True,
            })
            con.execute(
                "UPDATE projects SET status='failed',last_audit_json=?,updated_at=? WHERE id=?",
                (json.dumps(previous, ensure_ascii=False), core.now_iso(), project_id),
            )
    finally:
        _import_tasks.pop(project_id, None)


def _start_import_task(project_id: str) -> bool:
    task = _import_tasks.get(project_id)
    if task and not task.done():
        return False
    _import_tasks[project_id] = asyncio.create_task(_process_staged_import(project_id))
    return True


@core.app.on_event("startup")
async def resume_interrupted_site_imports() -> None:
    # ZIP payloads are persisted before the HTTP response, so an API restart
    # can safely continue an interrupted import instead of regenerating a site.
    with core.db() as con:
        rows = con.execute(
            "SELECT id,status,config_json FROM projects WHERE status IN ('importing','repository_ready','auditing')"
        ).fetchall()
    for row in rows:
        try:
            cfg = json.loads(row["config_json"] or "{}")
        except Exception:
            cfg = {}
        if cfg.get("_imported_site") and _stage_dir(row["id"]).is_dir():
            _start_import_task(row["id"])


@core.app.post("/imports/site")
async def import_site_zip(
    file: UploadFile = File(...),
    name: str = Form(default="Imported website"),
    organization: str = Form(default=""),
    package: str = Form(default="Standard"),
    goal: str = Form(default="Improve and maintain this imported website."),
    audience: str = Form(default=""),
    programme: str = Form(default="Existing website import"),
    user_id: str = Depends(core.current_user),
):
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(415, "Upload a .zip archive")
    if package not in {"Start", "Standard", "Premium"}:
        raise HTTPException(422, "Unknown package")

    raw = await file.read(MAX_ZIP_BYTES + 1)
    if len(raw) > MAX_ZIP_BYTES:
        raise HTTPException(413, "ZIP archive is too large")
    if not raw:
        raise HTTPException(400, "ZIP archive is empty")

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(415, "The uploaded file is not a valid ZIP archive") from exc

    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) > MAX_FILES:
        raise HTTPException(413, f"ZIP contains more than {MAX_FILES} files")

    extracted: dict[str, bytes] = {}
    expanded = 0
    for info in members:
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise HTTPException(422, "ZIP symlinks are not allowed")
        path = _normalise_member(info.filename)
        if not path:
            continue
        if info.file_size > MAX_FILE_BYTES:
            raise HTTPException(413, f"{path} exceeds the per-file import limit")
        expanded += int(info.file_size or 0)
        if expanded > MAX_EXPANDED_BYTES:
            raise HTTPException(413, "Expanded ZIP content is too large")
        # Block extreme compression ratios often seen in archive bombs.
        compressed = max(1, int(info.compress_size or 0))
        if info.file_size > 2_000_000 and (info.file_size / compressed) > 250:
            raise HTTPException(413, f"{path} has an unsafe compression ratio")
        data = archive.read(info)
        if len(data) != info.file_size:
            raise HTTPException(422, f"Could not safely read {path}")
        extracted[path] = data
    archive.close()

    extracted = _strip_common_root(extracted)
    if "index.html" not in {path.lower(): path for path in extracted}:
        # Normalize case only when an exact index page exists under another case.
        candidate = next((path for path in extracted if path.lower() == "index.html"), None)
        if candidate:
            extracted["index.html"] = extracted.pop(candidate)
        else:
            raise HTTPException(422, "Imported static site must contain index.html at its root")

    text_files: dict[str, str] = {}
    deliverable: dict[str, str | bytes] = {}
    for path, data in extracted.items():
        ext = PurePosixPath(path).suffix.lower()
        if ext in TEXT_EXTENSIONS:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(415, f"{path} is not UTF-8 text") from exc
            text_files[path] = text
            deliverable[path] = text
        else:
            deliverable[path] = data

    safe_name = _safe_name(name)
    project_id = str(uuid.uuid4())
    repo_slug = re.sub(r"[^a-z0-9-]+", "-", f"{core.GITHUB_OUTPUT_PREFIX}{safe_name}-import-{project_id[:8]}".lower()).strip("-")[:90]

    html_pages = []
    for path, content in sorted(text_files.items()):
        if not path.lower().endswith((".html", ".htm")):
            continue
        slug = "index" if path.lower() == "index.html" else PurePosixPath(path).stem
        html_pages.append({
            "slug": slug,
            "title": _title_from_html(content, "Home" if slug == "index" else slug.replace("-", " ").title()),
            "purpose": "Imported existing page",
        })

    config = {
        "name": safe_name,
        "organization": _safe_name(organization, safe_name),
        "package": package,
        "programme": _safe_name(programme, "Existing website import"),
        "language": "sl",
        "goal": _safe_name(goal, "Improve and maintain this imported website."),
        "audience": _safe_name(audience, ""),
        "tone": "preserve existing voice unless instructed otherwise",
        "brand": {
            "primary_color": "#123f35",
            "secondary_color": "#d9ff65",
            "background_color": "#ffffff",
            "text_color": "#102923",
            "font_style": "modern",
            "mood": "preserve imported design",
        },
        "pages": html_pages[:12],
        "hero_title": "",
        "hero_subtitle": "",
        "cta_text": "Kontaktirajte nas",
        "contact_email": None,
        "image_direction": "preserve imported media",
        "custom_requirements": "Imported from ZIP. Preserve working code and improve through focused revisions.",
        "_imported_site": {
            "source": file.filename or "website.zip",
            "files": len(deliverable),
            "expanded_bytes": expanded,
        },
    }

    manifest = {
        "project_id": project_id,
        "repo_slug": repo_slug,
        "safe_name": safe_name,
        "config": config,
        "files": len(deliverable),
        "pages": len(html_pages),
    }
    _write_stage(project_id, extracted, manifest)

    with core.db() as con:
        con.execute(
            "INSERT INTO projects(id,user_id,package,status,name,repo_name,config_json,last_audit_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                user_id,
                package,
                "importing",
                safe_name,
                repo_slug,
                json.dumps(config, ensure_ascii=False),
                json.dumps({
                    "issues": [],
                    "repository_ready": False,
                    "public_live": False,
                    "preview_ready": False,
                    "imported_source": True,
                    "imported_files": len(deliverable),
                    "import_stage": "accepted",
                }, ensure_ascii=False),
                core.now_iso(),
                core.now_iso(),
            ),
        )

    _start_import_task(project_id)
    return {
        "id": project_id,
        "repo_name": repo_slug,
        "status": "importing",
        "files": len(deliverable),
        "pages": len(html_pages),
        "accepted": True,
    }
