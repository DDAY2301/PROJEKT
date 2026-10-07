"""Second-pass design critic for local website planning.

The first model call plans the site. This critic independently reviews that
plan for hierarchy, conversion clarity, responsive section rhythm and content
density. It may reorganize sections, but it cannot change customer URLs/titles
or invent factual claims.
"""

from __future__ import annotations

import json
import os
from typing import Any

import api.main as core
import api.model_router as model_router

_base_design_site = core.design_site
ENABLED = os.getenv("DESIGN_CRITIC_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
MODE = os.getenv("DESIGN_CRITIC_MODE", "adaptive").strip().lower()


def _valid_sections(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not value:
        return None
    out: list[dict[str, Any]] = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or "").strip()
        body = str(item.get("body") or "").strip()
        if not heading or not body:
            continue
        section = {
            "type": str(item.get("type") or "content")[:40],
            "heading": heading[:180],
            "body": body[:2200],
        }
        if item.get("cta"):
            section["cta"] = str(item.get("cta"))[:120]
        if item.get("image_prompt"):
            section["image_prompt"] = str(item.get("image_prompt"))[:300]
        out.append(section)
    return out or None


def _plan_needs_critic(spec: dict[str, Any]) -> bool:
    pages = [p for p in (spec.get("pages") or []) if isinstance(p, dict)]
    if not pages:
        return True
    for page in pages:
        sections = [s for s in (page.get("sections") or []) if isinstance(s, dict)]
        if len(sections) < 3:
            return True
        headings = []
        body_chars = 0
        for section in sections[:6]:
            heading = str(section.get("heading") or "").strip().lower()
            body = str(section.get("body") or "").strip()
            if heading:
                headings.append(heading)
            body_chars += len(body)
        if body_chars < 120:
            return True
        if len(headings) != len(set(headings)):
            return True
    return False


async def design_site_with_critic(config: dict[str, Any]) -> dict[str, Any]:
    spec = await _base_design_site(config)
    if not ENABLED or MODE in {"off", "disabled", "never"}:
        return spec
    if MODE == "adaptive" and not _plan_needs_critic(spec):
        spec["_critic"] = {"score": None, "issues": [], "version": "design-critic-v2-adaptive", "skipped": True}
        return spec

    compact_config = {
        key: config.get(key)
        for key in (
            "name", "organization", "package", "programme", "language", "goal",
            "audience", "tone", "pages", "hero_title", "hero_subtitle",
            "cta_text", "image_direction", "custom_requirements", "_quality_memory",
        )
        if key in config
    }
    prompt = f"""
Review this website plan as a strict senior design director.
CUSTOMER={json.dumps(compact_config, ensure_ascii=False)}
CURRENT_PLAN={json.dumps(spec, ensure_ascii=False)}

Return strict JSON:
{{
  "score": 0-100,
  "issues": ["short concrete issue", ...],
  "revised_pages": [
    {{"sections":[{{"type":"...","heading":"...","body":"...","cta":"optional"}}]}}
  ]
}}

Rules:
- preserve the exact number and order of pages
- do not change page slugs, page titles or customer facts
- never invent partners, awards, funding, statistics, addresses or contact facts
- improve section hierarchy, content rhythm, CTA clarity and mobile-readiness
- avoid generic repetitive section patterns
- use the customer's own supplied facts only
- if the current plan is already strong, keep its sections substantially intact
"""
    try:
        raw = core.strip_fence(await model_router.generate(
            prompt,
            "You are an independent website design critic. Return one valid JSON object only.",
            json_mode=True,
            timeout=180,
            num_predict=1500,
            temperature=0.10,
            num_ctx=6144,
            tier="fast",
        ))
        data = json.loads(raw)
        revised = data.get("revised_pages")
        pages = spec.get("pages") or []
        if not isinstance(revised, list) or len(revised) != len(pages):
            return spec

        next_pages: list[dict[str, Any]] = []
        for index, page in enumerate(pages):
            original = dict(page)
            candidate = revised[index] if isinstance(revised[index], dict) else {}
            sections = _valid_sections(candidate.get("sections"))
            if sections:
                original["sections"] = sections
            next_pages.append(original)

        return {
            **spec,
            "pages": next_pages,
            "_critic": {
                "score": data.get("score"),
                "issues": [str(x)[:240] for x in (data.get("issues") or []) if isinstance(x, (str, int, float))][:12],
                "version": "design-critic-v2-adaptive", "skipped": False,
            },
        }
    except Exception:
        # Critic quality must never become a single point of failure.
        return spec


core.design_site = design_site_with_critic
