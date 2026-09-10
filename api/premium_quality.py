"""Deterministic quality gate for premium generated websites.

Model review is useful but not sufficient. These checks reject known classes of
low-quality output before publishing: raw language markers, weak page structure,
broken/placeholder links, missing responsive design primitives, fake contact
details and regressions to generic template CSS.
"""

from __future__ import annotations

import json
import re
from typing import Any

import api.main as core

_base_ai_audit = core.ai_audit


def _issue(severity: str, code: str, file: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "file": file, "message": message}


def _normal_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _deterministic_quality(files: dict[str, str], config: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    css = files.get("assets/site.css", "")
    index = files.get("index.html", "")
    brief = json.dumps(config, ensure_ascii=False).lower()
    brief_digits = _normal_digits(brief)

    for path, content in files.items():
        if path.endswith(".html"):
            stripped = content.lstrip("\ufeff\r\n\t ")
            if re.match(r"^html\s*\n", stripped, re.I):
                issues.append(_issue("critical", "RAW_LANGUAGE_MARKER", path, "HTML starts with a raw language marker instead of <!doctype html>."))
            low = content.lower()
            if "<!doctype html" not in low or "<main" not in low or "</html>" not in low:
                issues.append(_issue("critical", "HTML_SHELL_INVALID", path, "Page is missing the complete semantic HTML document shell."))
            if "assets/site.css" not in low:
                issues.append(_issue("critical", "STYLESHEET_MISSING", path, "Page does not load the shared design system."))
            if 'href="#"' in low or "href='#'" in low:
                issues.append(_issue("high", "PLACEHOLDER_LINK", path, "Page contains a placeholder # link instead of a real destination."))
            if "<header" not in low or "<footer" not in low or "<nav" not in low:
                issues.append(_issue("high", "LAYOUT_CHROME_MISSING", path, "Page must include consistent header, navigation and footer."))

            # Reject invented international-style phone numbers unless their digits
            # are present in the customer's own brief/configuration.
            for phone in re.findall(r"\+\d[\d\s().-]{7,}\d", content):
                digits = _normal_digits(phone)
                if len(digits) >= 8 and digits not in brief_digits:
                    issues.append(_issue("critical", "UNSUPPORTED_CONTACT_FACT", path, "A phone number was invented that is not present in the customer brief."))
                    break
            if re.search(r"(?:address|naslov)\s*:\s*[^<\n]{6,}", content, re.I) and not re.search(r'"(?:address|naslov)"\s*:', brief, re.I):
                issues.append(_issue("high", "UNSUPPORTED_ADDRESS", path, "A physical address appears although none was supplied in the customer brief."))

    if css:
        stripped_css = css.lstrip("\ufeff\r\n\t ")
        if re.match(r"^css\s*\n", stripped_css, re.I):
            issues.append(_issue("critical", "RAW_LANGUAGE_MARKER", "assets/site.css", "CSS starts with a raw language marker."))
        if len(css) < 4500:
            issues.append(_issue("high", "DESIGN_SYSTEM_TOO_THIN", "assets/site.css", "The stylesheet is too small to meet the premium multi-page design floor."))
        for required in ("@media", ":focus-visible", "--primary", ".site-header", ".hero"):
            if required not in css:
                issues.append(_issue("high", "DESIGN_SYSTEM_MISSING", "assets/site.css", f"Premium design primitive is missing: {required}."))
        if re.search(r"font-family\s*:\s*['\"]Editorial['\"]", css, re.I):
            issues.append(_issue("high", "INVALID_FONT", "assets/site.css", "The stylesheet references the non-standard 'Editorial' font without providing it."))
        if re.search(r"footer[^{}]*\{[^}]*position\s*:\s*fixed", css, re.I | re.S):
            issues.append(_issue("high", "FIXED_FOOTER", "assets/site.css", "A fixed footer can obscure content and is not accepted by the premium design floor."))
    else:
        issues.append(_issue("critical", "DESIGN_SYSTEM_MISSING", "assets/site.css", "Shared CSS design system is missing."))

    if index:
        low = index.lower()
        section_count = len(re.findall(r"<section\b", low))
        if section_count < 5:
            issues.append(_issue("high", "HOME_TOO_SHALLOW", "index.html", f"Homepage has only {section_count} meaningful sections; premium pages require richer narrative structure."))
        if "<h1" not in low or "class=\"hero" not in low and "class='hero" not in low:
            issues.append(_issue("high", "HERO_MISSING", "index.html", "Homepage needs a designed hero with a single primary heading."))
        if "viewport" not in low:
            issues.append(_issue("critical", "VIEWPORT_MISSING", "index.html", "Responsive viewport metadata is missing."))

    return issues


async def ai_audit(files: dict[str, str], config: dict[str, Any]) -> dict[str, Any]:
    try:
        model_result = await _base_ai_audit(files, config)
    except Exception:
        model_result = {"issues": []}
    issues = list(model_result.get("issues") or [])
    issues.extend(_deterministic_quality(files, config))

    # De-duplicate by code+file+message while preserving the more useful model
    # findings alongside deterministic blockers.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in issues:
        key = (str(item.get("code") or ""), str(item.get("file") or ""), str(item.get("message") or ""))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return {**model_result, "issues": unique, "quality_floor": "premium-v1"}


core.ai_audit = ai_audit
