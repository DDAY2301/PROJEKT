"""Compact industry-aware art-direction prompt for existing website planner.

No additional model or render pipeline. Brief data remains untrusted; the result
describes visual style, never creates unverifiable customer claims.
"""
from __future__ import annotations

import json
from typing import Any

DESIGN_PROMPT_VERSION = "art-direction-v4"

# Specific composition, typography and image direction. The deterministic
# Design Engine remains responsible for actual CSS and originality controls.
INDUSTRY_DIRECTIONS = (
    (("law", "legal", "attorney", "odvet", "pravni"), "legal", "Calm institutional editorial; strong typography, asymmetric text/image hero, restrained ink/stone palette, clearly separated services and credentials.",),
    (("restaurant", "food", "hotel", "hospitality", "gostin", "restavr", "kavarn"), "hospitality", "Warm editorial hospitality; atmospheric authentic photography, spacious menu/story hierarchy, prominent booking/contact path, tactile type pairing.",),
    (("cleaning", "clean", "service", "servis", "čist", "čišč", "salon"), "local_service", "Warm trustworthy local service; crisp typography, genuine service photography, scannable prices/process, visible quote CTA, no stock-office aesthetic.",),
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
    """Brief-specific art director shared by planner, critic, CSS and page writer."""
    import hashlib

    industry, direction = select_direction(config)
    # A stable motif per project discourages cross-project layout repetition
    # without extra model calls or unpredictable random decisions.
    identity = " | ".join(str(config.get(key) or "") for key in
                          ("organization", "name", "programme"))
    motifs = (
        "editorial split hero / staggered image-content rhythm",
        "image-led hero / spacious numbered narrative",
        "typography-led hero / contrasting full-bleed feature",
        "asymmetric grid / calm proof-and-process sections",
        "story-led hero / restrained mosaic of relevant imagery",
    )
    digest = hashlib.sha256(identity.encode("utf-8")).digest()[0]
    motif = motifs[digest % len(motifs)]
    template_id = str(config.get("_design_template_id") or "").strip().upper()
    template_name = str(config.get("_design_template_name") or "").strip()[:60]
    composition = str(config.get("_design_composition") or "").strip()[:30]
    selection = f"Template {template_id} {template_name}; composition={composition}. " if template_id else ""
    return (
        f"{DESIGN_PROMPT_VERSION}/{industry}: {direction} "
        f"{selection}Compositional motif: {motif}. "
        "Use only THIS brief's brand, images, names and contacts; never copy clients. "
        "Mobile-first with accessible contrast, keyboard focus, real CTAs and photo crops. "
        "No generic SaaS cards, fake reviews/claims, phantom assets, repeated copy "
        "or invented metrics. Preserve stated colours, language and verified facts."
    )


def render_direction(config: dict[str, Any], page: dict[str, Any] | None = None) -> str:
    """Extra low-token constraints for actual CSS/HTML generation, not just planning."""
    route = str((page or {}).get("slug") or "index")[:50]
    purpose = str((page or {}).get("purpose") or "")[:140]
    return (
        f"{design_direction(config)} Page={route}; purpose={purpose}. "
        "Vary actual hero geometry, navigation, editorial section rhythm, image crops "
        "and type pairing to fit THIS client; do not merely recolour a common layout. "
        "Keep navigation/CTA destinations and forms real; use available licensed "
        "assets only. Check 360/390/430/768/1024/1440/1920px, keyboard focus "
        "and reduced-motion. No unverified claims, fake reviews or mock submissions."
    )
