"""Concise repository map for local-model editing.

Inspired by repository-map approaches used by modern coding agents: the local
model gets a compact view of file roles and important symbols before seeing
full file contents. This reduces context pressure and helps revisions respect
existing structure without sending unnecessary source.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import PurePosixPath
from typing import Any

_TEXT_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json", ".xml", ".md", ".txt", ".svg"}


def _clean(value: str, limit: int = 90) -> str:
    value = re.sub(r"\s+", " ", unescape(value or "")).strip()
    return value[:limit]


def _html_summary(content: str) -> list[str]:
    out: list[str] = []
    title = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
    if title:
        out.append(f"title={_clean(title.group(1))}")
    headings = [
        _clean(re.sub(r"<[^>]+>", " ", text))
        for _tag, text in re.findall(r"<(h[1-3])[^>]*>(.*?)</\1>", content, re.I | re.S)
    ]
    headings = [x for x in headings if x][:8]
    if headings:
        out.append("headings=" + " | ".join(headings))
    ids = list(dict.fromkeys(re.findall(r'\bid=["\']([A-Za-z0-9_-]{1,80})["\']', content)))[:10]
    if ids:
        out.append("ids=" + ", ".join(ids))
    forms = len(re.findall(r"<form\b", content, re.I))
    images = len(re.findall(r"<img\b|<picture\b", content, re.I))
    if forms or images:
        out.append(f"forms={forms}, media={images}")
    return out


def _css_summary(content: str) -> list[str]:
    selectors: list[str] = []
    for raw in re.findall(r"(?:^|\})([^@{}][^{}]{0,180})\{", content, re.M):
        cleaned = _clean(raw, 70)
        if cleaned and cleaned not in selectors:
            selectors.append(cleaned)
        if len(selectors) >= 14:
            break
    vars_ = list(dict.fromkeys(re.findall(r"--([A-Za-z0-9_-]+)\s*:", content)))[:12]
    out: list[str] = []
    if selectors:
        out.append("selectors=" + " | ".join(selectors))
    if vars_:
        out.append("css-vars=" + ", ".join(vars_))
    if "@media" in content:
        out.append("responsive=yes")
    return out


def _js_summary(content: str) -> list[str]:
    names: list[str] = []
    patterns = [
        r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(",
        r"\bclass\s+([A-Za-z_$][\w$]*)\b",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>",
    ]
    for pattern in patterns:
        for name in re.findall(pattern, content):
            if name not in names:
                names.append(name)
            if len(names) >= 18:
                break
        if len(names) >= 18:
            break
    endpoints = list(dict.fromkeys(re.findall(r'["\'](/(?:api/)?[A-Za-z0-9_./{}:-]+)["\']', content)))[:10]
    out: list[str] = []
    if names:
        out.append("symbols=" + ", ".join(names))
    if endpoints:
        out.append("routes=" + ", ".join(endpoints))
    if "addEventListener" in content:
        out.append("events=yes")
    return out


def summarize_file(path: str, content: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    bits: list[str] = []
    if ext in {".html", ".htm"}:
        bits = _html_summary(content)
    elif ext == ".css":
        bits = _css_summary(content)
    elif ext in {".js", ".mjs", ".cjs"}:
        bits = _js_summary(content)
    elif ext == ".json":
        try:
            import json
            data: Any = json.loads(content)
            if isinstance(data, dict):
                bits = ["keys=" + ", ".join(list(map(str, data.keys()))[:16])]
        except Exception:
            pass
    elif ext in {".md", ".txt"}:
        headings = [_clean(x) for x in re.findall(r"^#{1,3}\s+(.+)$", content, re.M)][:8]
        if headings:
            bits = ["headings=" + " | ".join(headings)]
    suffix = " ; ".join(bits)
    return f"{path} :: {suffix}" if suffix else path


def build_repo_map(files: dict[str, str], max_chars: int = 12000) -> str:
    """Return a bounded, deterministic repository map for model context."""
    candidates = [
        (path, content)
        for path, content in files.items()
        if isinstance(content, str) and PurePosixPath(path).suffix.lower() in _TEXT_EXTENSIONS
    ]
    priority = {".html": 0, ".htm": 0, ".css": 1, ".js": 2, ".mjs": 2, ".cjs": 2, ".json": 3}
    candidates.sort(key=lambda item: (priority.get(PurePosixPath(item[0]).suffix.lower(), 9), item[0]))

    lines = [
        "REPOSITORY MAP",
        "Use this map to understand the existing site before editing. Preserve unrelated structure.",
    ]
    used = sum(len(x) + 1 for x in lines)
    for path, content in candidates[:100]:
        line = "- " + summarize_file(path, content)
        if used + len(line) + 1 > max_chars:
            lines.append("- … map truncated …")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
