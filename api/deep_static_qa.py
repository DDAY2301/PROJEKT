"""Offline deterministic bundle QA.

These checks complement model review and Chromium visual QA. They operate only
on the generated/imported source bundle and therefore remain usable with a fully
local agent and no network access.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath
from typing import Any

import api.main as core

_base_static_audit = core.static_audit

TEXT_LIMITS = {
    ".html": 320_000,
    ".htm": 320_000,
    ".css": 320_000,
    ".js": 360_000,
    ".mjs": 360_000,
    ".cjs": 360_000,
}
CHECKABLE_TARGET_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json", ".xml", ".webmanifest"}


def _issue(severity: str, code: str, file: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "file": file, "message": message}


def _resolve(source: str, target: str) -> str | None:
    target = (target or "").strip()
    if not target or target.startswith(("#", "mailto:", "tel:", "data:", "blob:", "javascript:", "//")):
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None
    if target.startswith("/"):
        path = target.lstrip("/")
    else:
        path = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
    if path.endswith("/"):
        path += "index.html"
    return path


def _accessible_name(tag: str) -> bool:
    low = tag.lower()
    if re.search(r"aria-label\s*=\s*['\"][^'\"]+['\"]", low):
        return True
    if re.search(r"aria-labelledby\s*=\s*['\"][^'\"]+['\"]", low):
        return True
    inner = re.sub(r"<[^>]+>", " ", tag)
    return bool(re.sub(r"\s+", " ", inner).strip())


def deep_checks(files: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    paths = set(files.keys())

    for path, raw in files.items():
        if not isinstance(raw, str):
            continue
        ext = PurePosixPath(path).suffix.lower()
        limit = TEXT_LIMITS.get(ext)
        if limit and len(raw.encode("utf-8")) > limit:
            issues.append(_issue(
                "medium",
                "SOURCE_FILE_TOO_LARGE",
                path,
                f"Source file exceeds the maintainability budget of {limit // 1000} KB.",
            ))

        if ext not in {".html", ".htm"}:
            continue

        ids = re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', raw, re.I)
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            issues.append(_issue(
                "high",
                "DUPLICATE_ID",
                path,
                "Duplicate HTML id values: " + ", ".join(duplicates[:6]),
            ))

        for attr, target in re.findall(r'\b(href|src)\s*=\s*["\']([^"\']+)["\']', raw, re.I):
            resolved = _resolve(path, target)
            if not resolved:
                continue
            suffix = PurePosixPath(resolved).suffix.lower()
            # Image/font references may be attached later by the media pipeline;
            # deterministic link checks focus on source dependencies and pages.
            if suffix not in CHECKABLE_TARGET_EXTENSIONS:
                continue
            if resolved not in paths:
                issues.append(_issue(
                    "high" if attr.lower() == "src" else "medium",
                    "BROKEN_INTERNAL_REFERENCE",
                    path,
                    f"Local {attr.lower()} target does not exist in the bundle: {target}",
                ))

        for anchor in re.findall(r"<a\b[^>]*>.*?</a>", raw, re.I | re.S):
            if re.search(r'target\s*=\s*["\']_blank["\']', anchor, re.I):
                rel = re.search(r'rel\s*=\s*["\']([^"\']*)["\']', anchor, re.I)
                tokens = set((rel.group(1).lower().split() if rel else []))
                if "noopener" not in tokens:
                    issues.append(_issue(
                        "medium",
                        "EXTERNAL_TAB_NO_NOOPENER",
                        path,
                        "A target=_blank link is missing rel=noopener.",
                    ))
                    break
            if not _accessible_name(anchor):
                issues.append(_issue(
                    "high",
                    "LINK_NO_ACCESSIBLE_NAME",
                    path,
                    "A visible link has no accessible name.",
                ))
                break

        for button in re.findall(r"<button\b[^>]*>.*?</button>", raw, re.I | re.S):
            if not _accessible_name(button):
                issues.append(_issue(
                    "high",
                    "BUTTON_NO_ACCESSIBLE_NAME",
                    path,
                    "A button has no accessible name.",
                ))
                break

        # Simple label coverage: controls with an id should have a matching
        # explicit label or their own aria-label/aria-labelledby.
        labels = set(re.findall(r'<label\b[^>]*for\s*=\s*["\']([^"\']+)["\']', raw, re.I))
        for control in re.findall(r"<(?:input|select|textarea)\b[^>]*>", raw, re.I):
            if re.search(r'type\s*=\s*["\']hidden["\']', control, re.I):
                continue
            cid = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', control, re.I)
            named = re.search(r'aria-(?:label|labelledby)\s*=\s*["\'][^"\']+["\']', control, re.I)
            if cid and cid.group(1) not in labels and not named:
                issues.append(_issue(
                    "medium",
                    "FORM_CONTROL_UNLABELLED",
                    path,
                    f"Form control #{cid.group(1)} has no explicit label or ARIA name.",
                ))
                break

        h1_count = len(re.findall(r"<h1\b", raw, re.I))
        if h1_count > 1:
            issues.append(_issue(
                "medium",
                "MULTIPLE_H1",
                path,
                f"Page contains {h1_count} H1 elements; keep one primary page heading.",
            ))

    # De-duplicate deterministic findings.
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in issues:
        key = (item["code"], item["file"], item["message"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def static_audit(files: dict[str, Any]) -> dict[str, Any]:
    text_only = {path: value for path, value in files.items() if isinstance(value, str)}
    base = _base_static_audit(text_only)
    issues = list(base.get("issues") or []) + deep_checks(files)
    passed = not any(item.get("severity") in {"critical", "high"} for item in issues)
    return {**base, "passed": passed, "issues": issues, "deterministic_qa": "bundle-v2"}


core.static_audit = static_audit
