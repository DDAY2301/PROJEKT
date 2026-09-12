"""Local multimodal design review layered on top of deterministic Visual QA.

Chromium catches measurable regressions. A small local vision model reviews the
actual rendered screenshots for the things DOM metrics cannot judge reliably:
visual hierarchy, balance, spacing rhythm, image crops, perceived polish and
cross-device consistency. Everything stays on the user's machine through
Ollama; no screenshot or customer content is sent to a paid/cloud model.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

import api.visual_qa as visual_qa

_base_audit_files = visual_qa.audit_files
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
VISION_MODEL = os.getenv("VISUAL_QA_MODEL", "qwen2.5vl:3b").strip()
VISION_ENABLED = os.getenv("VISUAL_QA_VISION", "true").strip().lower() in {"1", "true", "yes", "on"}
MAX_VISION_PAGES = int(os.getenv("VISUAL_QA_VISION_MAX_PAGES", "12"))

ALLOWED_CATEGORIES = {
    "hierarchy", "spacing", "typography", "imagery", "consistency",
    "cta", "navigation", "responsive", "polish", "composition",
}


def _issue(severity: str, code: str, file: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "file": file, "message": message}


def _crop_for_review(image: Image.Image, max_height: int) -> Image.Image:
    if image.height > max_height:
        return image.crop((0, 0, image.width, max_height))
    return image.copy()


def _scaled(image: Image.Image, width: int) -> Image.Image:
    if image.width == width:
        return image.copy()
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _review_montage(screenshots: list[dict[str, Any]], page_file: str) -> bytes | None:
    by_viewport = {str(x.get("viewport")): x for x in screenshots if x.get("file") == page_file}
    desktop_meta = by_viewport.get("desktop")
    mobile_meta = by_viewport.get("mobile")
    if not desktop_meta or not mobile_meta:
        return None
    desktop_path = Path(str(desktop_meta.get("path") or ""))
    mobile_path = Path(str(mobile_meta.get("path") or ""))
    if not desktop_path.is_file() or not mobile_path.is_file():
        return None

    try:
        with Image.open(desktop_path) as d0, Image.open(mobile_path) as m0:
            desktop = _scaled(_crop_for_review(d0.convert("RGB"), 2300), 900)
            mobile = _scaled(_crop_for_review(m0.convert("RGB"), 1800), 360)

            # Add a compact full-page overview beneath the two top-of-page crops.
            full = d0.convert("RGB")
            full_thumb = _scaled(full, 900)
            if full_thumb.height > 1450:
                full_thumb = full_thumb.resize((900, 1450), Image.Resampling.LANCZOS)

            gap = 24
            label_h = 40
            top_h = max(desktop.height, mobile.height)
            canvas_w = 900 + gap + 360
            canvas_h = label_h + top_h + gap + label_h + full_thumb.height
            canvas = Image.new("RGB", (canvas_w, canvas_h), "#eef1ee")
            draw = ImageDraw.Draw(canvas)
            draw.text((8, 10), "DESKTOP TOP / MOBILE TOP", fill="#102923")
            canvas.paste(desktop, (0, label_h))
            canvas.paste(mobile, (900 + gap, label_h))
            y = label_h + top_h + gap
            draw.text((8, y + 10), "DESKTOP FULL-PAGE OVERVIEW", fill="#102923")
            canvas.paste(full_thumb, (0, y + label_h))

            out = io.BytesIO()
            canvas.save(out, format="JPEG", quality=82, optimize=True)
            return out.getvalue()
    except (OSError, ValueError):
        return None


def _normalise_review(raw: Any, page_file: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("vision review was not a JSON object")
    try:
        score = int(round(float(raw.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    issues: list[dict[str, str]] = []
    for item in raw.get("issues") or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"high", "medium", "low"}:
            severity = "medium"
        category = re.sub(r"[^a-z]+", "", str(item.get("category") or "polish").lower())
        if category not in ALLOWED_CATEGORIES:
            category = "polish"
        message = re.sub(r"\s+", " ", str(item.get("message") or "")).strip()[:360]
        if not message:
            continue
        issues.append(_issue(severity, f"VISUAL_AI_{category.upper()}", page_file, message))
    summary = re.sub(r"\s+", " ", str(raw.get("summary") or "")).strip()[:420]
    return {"file": page_file, "score": score, "summary": summary, "issues": issues}


async def _review_page(client: httpx.AsyncClient, page_file: str, jpeg: bytes, config: dict[str, Any]) -> dict[str, Any]:
    context = {
        "site_name": config.get("name") or config.get("organization") or "Website",
        "audience": config.get("audience") or "",
        "tone": config.get("tone") or "",
        "mood": (config.get("brand") or {}).get("mood") or "",
        "page": page_file,
    }
    prompt = f"""You are a strict senior art director reviewing a finished paid website.
The attached image is a QA montage of the SAME page: desktop top, mobile top, and a compact desktop full-page overview.
Project context: {json.dumps(context, ensure_ascii=False)}

Judge only what is visibly supported by the screenshot. Do not invent missing content or facts.
Review:
- hierarchy and composition
- spacing rhythm and alignment
- typography and readability
- image crop/placement and visual balance
- navigation and CTA prominence
- desktop/mobile consistency
- whether the result looks intentional, contemporary and client-ready rather than like raw/template HTML

Severity rules:
- high: clearly unsuitable for a paying client or a major visible design/responsive flaw that should block publishing
- medium: clear professional-quality weakness that should be repaired if possible
- low: optional polish only

Return strict JSON only:
{{"score":0-100,"summary":"one short sentence","issues":[{{"severity":"high|medium|low","category":"hierarchy|spacing|typography|imagery|consistency|cta|navigation|responsive|polish|composition","message":"specific visible problem and how to improve it"}}]}}
A strong professional page should normally score 85+. Do not manufacture issues merely to lower the score.
"""
    payload = {
        "model": VISION_MODEL,
        "stream": False,
        "format": "json",
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(jpeg).decode("ascii")],
        }],
        "options": {"temperature": 0.1, "num_predict": 650},
    }
    response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"vision model returned HTTP {response.status_code}")
    data = response.json()
    content = str(((data.get("message") or {}).get("content")) or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I | re.S).strip()
    return _normalise_review(json.loads(content), page_file)


async def _vision_reviews(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if not VISION_ENABLED or not VISION_MODEL or not report.get("available"):
        return {"available": False, "model": VISION_MODEL, "reviews": [], "issues": []}
    screenshots = list(report.get("screenshots") or [])
    files: list[str] = []
    for shot in screenshots:
        name = str(shot.get("file") or "")
        if name and name not in files:
            files.append(name)
    files = files[:MAX_VISION_PAGES]
    if not files:
        return {"available": False, "model": VISION_MODEL, "reviews": [], "issues": []}

    reviews: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(150.0, connect=10.0)) as client:
        # Run sequentially so a 6 GB laptop GPU never has multiple vision
        # generations competing for VRAM. Ollama can swap the coder/vision model.
        for page_file in files:
            jpeg = await asyncio.to_thread(_review_montage, screenshots, page_file)
            if not jpeg:
                continue
            try:
                reviews.append(await _review_page(client, page_file, jpeg, config))
            except Exception as exc:
                return {
                    "available": False,
                    "model": VISION_MODEL,
                    "reviews": reviews,
                    "issues": [],
                    "error": str(exc)[:260],
                }

    issues = [issue for review in reviews for issue in (review.get("issues") or [])]
    scores = [int(review["score"]) for review in reviews if isinstance(review.get("score"), int)]
    return {
        "available": bool(reviews),
        "model": VISION_MODEL,
        "score": round(sum(scores) / len(scores)) if scores else None,
        "reviews": reviews,
        "issues": issues,
    }


async def audit_files_with_vision(
    files: dict[str, Any],
    project_id: str,
    config: dict[str, Any],
    uploaded_images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = await _base_audit_files(files, project_id, config, uploaded_images)
    vision = await _vision_reviews(report, config)
    report["vision"] = vision
    if vision.get("available"):
        report.setdefault("issues", []).extend(vision.get("issues") or [])
        deterministic = int(report.get("score") or 0)
        vision_score = int(vision.get("score") or deterministic)
        # Aesthetic review carries slightly more weight; measurable breakage is
        # still represented separately as high/critical blocking issues.
        report["score"] = round(deterministic * 0.4 + vision_score * 0.6)
        report["passed"] = not any(
            item.get("severity") in {"critical", "high"}
            for item in (report.get("issues") or [])
        )
        report["version"] = "visual-qa-v2-vision"
    return report


visual_qa.audit_files = audit_files_with_vision
