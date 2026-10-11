"""Compact industry-aware art-direction prompt for existing website planner.

No additional model or render pipeline. Brief data remains untrusted; the result
describes visual style, never creates unverifiable customer claims.
"""
from __future__ import annotations

import json
from typing import Any

DESIGN_PROMPT_VERSION = "art-direction-v3"

# Specific composition, typography and image direction. The deterministic
# Design Engine remains responsible for actual CSS and originality controls.
INDUSTRY_DIRECTIONS = (
    (("law", "legal", "attorney", "odvet", "pravni"), "legal", "Calm institutional editorial; strong typography, asymmetric text/image hero, restrained ink/stone palette, clearly separated services and credentials.",),
    (("restaurant", "food", "hotel", "hospitality", "gostin", "restavr", "kavarn"), "hospitality", "Warm editorial hospitality; atmospheric authentic photography, spacious menu/story hierarchy, prominent booking/contact path, tactile type pairing.",),
    (("cleaning", "service", "servis", "čist", "salon"), "local_service", "Warm trustworthy local service; crisp typography, genuine service photography, scannable prices/process, visible quote CTA, no stock-office aesthetic.",),
    (("forest", "outdoor", "survival", "nature", "planin", "gozd"), "outdoor", "Nature-led field journal; documentary outdoor imagery, earthy restrained accents, textured hierarchy, clear course/activities path.",),
    (("youth", "erasmus", "ngo", "nonprofit", "mladin", "zavod"), "social_impact", "Human-centred impact editorial; real activity photography, lively yet accessible hierarchy, participant pathways, honest programme evidence.",),
    (("auto", "car", "detail", "garage", "vozil", "avto"), "automotive", "Precision automotive studio; high-contrast typography, close-up material or vehicle images, strong service proof and booking journey.",),
    (("saas", "software", "platform", "cloud", "digital", "tech"), "technology", "Product-led technical editorial; clear functional diagrams/UI imagery when available, sharp hierarchy, restrained accents, legible feature demos.",),
    (("art", "design", "atelier", "craft", "studio", "archit", "interior"), "creative", "Premium studio portfolio; generous whitespace, considered grids, portfolio-first image crops, refined typography, quiet client enquiry route.",),
)
DEFAULT_DIRECTION = "Specific contemporary editorial layout, purposeful visual hierarchy, natural brand-matched palette, authentic relevant imagery and one clear conversion path."


def _safe_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:2200].lower()
    return str(value or "")[:700].lower()


def select_direction(config: dict[str, Any]) -> tuple[str, str]:
    """Industry selection uses brief text only; never invents client data."""
    searchable = " ".join(
        _safe_text(config.get(key)) for key in
        ("programme", "goal", "audience", "name", "organization", "tone", "image_direction")
    )
    for keywords, industry, direction in INDUSTRY_DIRECTIONS:
        if any(word in searchable for word in keywords):
            return industry, direction
    return "editorial", DEFAULT_DIRECTION


def design_direction(config: dict[str, Any]) -> str:
    industry, direction = select_direction(config)
    return (
        f"{DESIGN_PROMPT_VERSION}/{industry}: {direction} "
        "Respect explicit brand colours, fonts, language and image instructions. "
        "Give each page a distinct purpose and section rhythm, with readable mobile "
        "type, strong contrast, functional CTAs and meaningful photo placement. "
        "No generic SaaS cards, fake reviews/metrics, repeated hero slogans, "
        "unlicensed imagery or empty decorations. Do not contradict customer facts."
    )
