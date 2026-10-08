"""Premium deterministic renderer for generated websites.

The local model remains responsible for information architecture and copy, but
visual quality is no longer delegated to raw model HTML/CSS. This module adds a
stable design floor inspired by strong contemporary editorial/project sites:
large art-directed heroes, disciplined grids, rich section rhythm, metrics,
cross-page discovery, accessible navigation, responsive behaviour and subtle
motion. It intentionally does not copy any third-party site's code or assets.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

import api.main as core
import api.robust_generation as base


def _e(value: Any, *, quote: bool = False) -> str:
    return html.escape(str(value or ""), quote=quote)


def _hex(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    return raw if re.fullmatch(r"#[0-9a-fA-F]{6}", raw) else fallback


def _rgb(hex_value: str) -> tuple[int, int, int]:
    value = hex_value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(hex_value: str) -> float:
    channels = []
    for value in _rgb(hex_value):
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _mix_hex(a: str, b: str, amount: float) -> str:
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    vals = (
        round(ar + (br - ar) * amount),
        round(ag + (bg - ag) * amount),
        round(ab + (bb - ab) * amount),
    )
    return "#" + "".join(f"{max(0, min(255, v)):02x}" for v in vals)


def _readable_on_dark(color: str, dark: str = "#071d18") -> str:
    if _contrast_ratio(color, dark) >= 4.5:
        return color
    for step in range(1, 11):
        candidate = _mix_hex(color, "#ffffff", step / 10)
        if _contrast_ratio(candidate, dark) >= 4.5:
            return candidate
    return "#ffffff"


def _best_text_on(color: str) -> str:
    dark = "#071d18"
    light = "#ffffff"
    return dark if _contrast_ratio(dark, color) >= _contrast_ratio(light, color) else light


def _strip_language_marker(text: str, language: str) -> str:
    """Remove the common local-model artefact `html`/`css` before real output."""
    text = (text or "").lstrip("\ufeff\n\r\t ")
    text = re.sub(rf"^(?:```)?{re.escape(language)}\s*(?:```)?\s*", "", text, count=1, flags=re.I)
    return text.lstrip()


def _href(slug: str) -> str:
    return "index.html" if slug == "index" else f"{slug}.html"


def _text(value: Any, fallback: str = "") -> str:
    raw = re.sub(r"\s+", " ", str(value or fallback)).strip()
    return raw



def _is_sl(config: dict[str, Any], spec: dict[str, Any] | None = None) -> bool:
    language = _text(config.get("language")).lower()
    if language:
        if language.startswith("sl") or "sloven" in language:
            return True
        if language.startswith("en") or "english" in language or "angles" in base._fold_text(language):
            return False
    pages = (spec or {}).get("pages") or config.get("pages") or []
    titles = " ".join(str(p.get("title") or "") for p in pages if isinstance(p, dict)).lower()
    return any(token in titles for token in ("domov", "o nas", "kontakt", "programi", "pristop", "galerija"))


_UI = {
    "sl": {
        "skip": "Preskoči na vsebino",
        "menu": "Odpri navigacijo",
        "primary_nav": "Glavna navigacija",
        "discover": "Poglej vsebino ↓",
        "explore": "Povezane vsebine",
        "open": "Odpri stran ↗",
        "next": "Naslednji korak",
        "navigate": "Navigacija",
        "footer_nav": "Navigacija v nogi",
        "contact": "Kontakt",
        "project": "Projekt",
        "footer_note": "Responsive · dostopno · hitro",
        "crosslinks": ("Poglej še druge vsebine.", "Nadaljuj raziskovanje.", "Še iz projekta."),
    },
    "en": {
        "skip": "Skip to content",
        "menu": "Open navigation menu",
        "primary_nav": "Primary navigation",
        "discover": "Discover more ↓",
        "explore": "Related pages",
        "open": "Open page ↗",
        "next": "Next step",
        "navigate": "Navigate",
        "footer_nav": "Footer navigation",
        "contact": "Contact",
        "project": "Project",
        "footer_note": "Responsive · accessible · lightweight",
        "crosslinks": ("Explore more.", "Continue the story.", "More from the project."),
    },
}


def _ui(config: dict[str, Any], key: str, spec: dict[str, Any] | None = None) -> Any:
    return _UI["sl" if _is_sl(config, spec) else "en"][key]



_SECTION_LABELS = {
    "sl": {
        "program-list": "Programi", "audience": "Za koga", "decision": "Izbira",
        "principles": "Pristop", "process": "Proces", "outcome": "Rezultat",
        "story": "Zgodba", "trust": "Zaupanje", "gallery": "Galerija",
        "visual-direction": "Vizualna smer", "gallery-note": "Pristop",
        "contact": "Kontakt", "form-fields": "Povpraševanje", "next-step": "Naslednji korak",
        "intro": "Uvod", "goal": "Cilj", "brief": "Bistvo",
        "key-points": "Poudarki", "highlights": "Poudarki", "purpose": "Namen",
    },
    "en": {
        "program-list": "Programmes", "audience": "For whom", "decision": "Choose",
        "principles": "Approach", "process": "Process", "outcome": "Outcome",
        "story": "Story", "trust": "Trust", "gallery": "Gallery",
        "visual-direction": "Visual direction", "gallery-note": "Approach",
        "contact": "Contact", "form-fields": "Enquiry", "next-step": "Next step",
        "intro": "Introduction", "goal": "Goal", "brief": "Essentials",
        "key-points": "Highlights", "highlights": "Highlights", "purpose": "Purpose",
    },
}


def _section_label(config: dict[str, Any], value: Any, spec: dict[str, Any] | None = None) -> str:
    raw = base._fold_text(value).replace(" ", "-")
    lang = "sl" if _is_sl(config, spec) else "en"
    return _SECTION_LABELS[lang].get(raw, _text(value, "Poudarki" if lang == "sl" else "Overview").replace("-", " ").title())


def _public_summary(page: dict[str, Any], fallback: str = "") -> str:
    meta = _text(page.get("meta_description"))
    purpose = _text(page.get("purpose"))
    instruction_prefixes = (
        "predstaviti ", "razloziti ", "vizualno prikazati ", "preprost ", "mocan prvi vtis",
        "show ", "explain ", "present ", "help the visitor ",
    )
    folded_meta = base._fold_text(meta)
    if meta and not any(folded_meta.startswith(base._fold_text(x)) for x in instruction_prefixes):
        return meta
    sections = [s for s in (page.get("sections") or []) if isinstance(s, dict)]
    for section in sections:
        body = _text(section.get("body"))
        if body:
            body = body.replace(" • ", ". ").replace("•", ". ")
            return re.sub(r"\s+", " ", body).strip()[:240]
    return fallback or purpose


def _brand_mark(site_name: str) -> str:
    words = re.findall(r"[A-Za-zÀ-ž0-9]+", site_name)
    if len(words) >= 2:
        return "".join(word[0] for word in words[:2]).upper()
    if words:
        clean = re.sub(r"[^A-Za-zÀ-ž0-9]", "", words[0])
        return clean[:2].upper()
    return "PV"


def _page_kind(page: dict[str, Any]) -> str:
    text = _text(page.get("slug")) + " " + _text(page.get("title"))
    low = base._fold_text(text)
    if any(x in low for x in ("kontakt", "contact", "stik")):
        return "contact"
    if any(x in low for x in ("galer", "gallery")):
        return "gallery"
    if any(x in low for x in ("program", "service", "storitev", "ponud")):
        return "programs"
    if any(x in low for x in ("pristop", "approach", "process", "metod")):
        return "approach"
    if any(x in low for x in ("o nas", "about", "onas")):
        return "about"
    return "home" if str(page.get("slug") or "") == "index" else "content"


def _find_page_href(spec: dict[str, Any], tokens: tuple[str, ...], fallback: str = "index.html") -> str:
    for page in spec.get("pages") or []:
        if not isinstance(page, dict):
            continue
        hay = base._fold_text(f"{page.get('slug','')} {page.get('title','')}")
        if any(base._fold_text(token) in hay for token in tokens):
            return _href(str(page.get("slug") or "index"))
    return fallback


def _sentences(value: Any, limit: int = 3) -> list[str]:
    raw = _text(value)
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+", raw)
    return [p.strip() for p in parts if p.strip()][:limit]


def _configured_brand(config: dict[str, Any]) -> dict[str, str]:
    brand = config.get("brand") or {}
    primary = _hex(brand.get("primary_color"), "#0B1F33")
    accent = _hex(brand.get("secondary_color"), "#C7FF4A")
    background = _hex(brand.get("background_color"), "#F7F4EC")
    text = _hex(brand.get("text_color"), "#10212B")
    dark = "#071d18"
    return {
        "primary": primary,
        "accent": accent,
        "accent_readable": _readable_on_dark(accent, dark),
        "accent_ink": _best_text_on(accent),
        "background": background,
        "text": text,
    }


def _navigation(spec: dict[str, Any], active_slug: str) -> str:
    items = []
    for p in spec.get("pages") or []:
        slug = str(p.get("slug") or "index")
        title = _e(p.get("title") or "Page")
        current = ' aria-current="page"' if slug == active_slug else ""
        items.append(f'<a href="{_e(_href(slug), quote=True)}"{current}>{title}</a>')
    return "".join(items)


def _metrics(config: dict[str, Any]) -> list[tuple[str, str]]:
    # Only surface figures that came from the user's own brief/requirements.
    source = " ".join(
        str(config.get(k) or "")
        for k in ("requirements", "goal", "hero_subtitle", "programme")
    )
    pattern = re.compile(r"(?<!\w)(\d[\d,.]*\+?%?)\s+([A-Za-zÀ-ž][A-Za-zÀ-ž\- ]{2,36})")
    found: list[tuple[str, str]] = []
    for number, label in pattern.findall(source):
        label = re.split(r"[.,;:\n]", label)[0].strip()
        if not label or len(label) > 34:
            continue
        pair = (number, label)
        if pair not in found:
            found.append(pair)
        if len(found) == 4:
            break
    return found


def _journey(config: dict[str, Any]) -> list[str]:
    source = json.dumps(config, ensure_ascii=False).lower()
    canonical = ["Discover", "Build", "Test", "Scale"]
    if all(word.lower() in source for word in canonical):
        return canonical
    return []


def _visual_variant(spec: dict[str, Any] | None, index: int) -> int:
    design = (spec or {}).get("design_system") if isinstance((spec or {}).get("design_system"), dict) else {}
    motif = str((design or {}).get("motif") or "")
    composition = str((design or {}).get("composition") or "")
    seed = f"{motif}|{composition}|{index}".encode("utf-8")
    return int(hashlib.sha256(seed).hexdigest()[:8], 16) % 8


def _render_visual(label: str, index: int = 0, spec: dict[str, Any] | None = None) -> str:
    safe = _e(label[:32] or "Explore")
    variant = _visual_variant(spec, index)
    return f'''<div class="visual visual-v{variant} visual-{index % 4}" aria-hidden="true">
      <div class="visual-grid"></div>
      <div class="visual-frame"></div>
      <div class="visual-axis"><i></i><i></i><i></i></div>
      <div class="visual-orb visual-orb-a"></div><div class="visual-orb visual-orb-b"></div>
      <div class="visual-bars"><i></i><i></i><i></i><i></i></div>
      <span class="visual-kicker">0{(index % 9) + 1}</span>
      <span class="visual-chip">{_e(((spec or {}).get("design_system") or {}).get("motif") or "studio")}</span>
      <strong>{safe}</strong><span class="visual-arrow">↗</span>
    </div>'''


def _render_crosslinks(config: dict[str, Any], spec: dict[str, Any], current_slug: str) -> str:
    current_page = next((p for p in (spec.get("pages") or []) if str(p.get("slug") or "") == current_slug), {})
    if _page_kind(current_page) == "contact":
        return ""

    candidates = [
        p for p in (spec.get("pages") or [])
        if isinstance(p, dict) and str(p.get("slug") or "index") != current_slug
    ]
    if not candidates:
        return ""

    # Deterministic rotation makes different pages discover different neighbours.
    seed = int(hashlib.sha256(current_slug.encode("utf-8")).hexdigest()[:8], 16)
    # Cross-link cards are useful discovery chrome, not mandatory content. Keep
    # them on home and only about half of deeper pages so the site's rhythm does
    # not repeat the same large component everywhere.
    if current_slug != "index" and seed % 2:
        return ""
    if candidates:
        offset = seed % len(candidates)
        candidates = candidates[offset:] + candidates[:offset]

    cards = []
    for idx, p in enumerate(candidates[:3]):
        slug = str(p.get("slug") or "index")
        title = _e(p.get("title") or "Page")
        purpose = _e(_public_summary(p, _text(p.get("purpose"), "")))
        cards.append(
            f'''<a class="story-card reveal" href="{_e(_href(slug), quote=True)}">
              {_render_visual(str(p.get("title") or "Page"), idx + seed % 5, spec)}
              <div class="story-card-copy"><span>{_e(_ui(config, "explore", spec))}</span><h3>{title}</h3><p>{purpose}</p><b>{_e(_ui(config, "open", spec))}</b></div>
            </a>'''
        )
    headings = _ui(config, "crosslinks", spec)
    heading = headings[seed % len(headings)]
    return f'''<section class="section section-ink related-section"><div class="shell">
      <div class="section-head reveal"><span class="label">{_e(_ui(config, "explore", spec))}</span><h2>{_e(heading)}</h2></div>
      <div class="story-grid">{''.join(cards)}</div>
    </div></section>'''

def _render_gallery_section(config: dict[str, Any], section: dict[str, Any], page: dict[str, Any], spec: dict[str, Any]) -> str:
    heading = _text(section.get("heading"), page.get("title") or "Gallery")
    body = _text(section.get("body"))
    items = [x.strip(" ·-•") for x in re.split(r"\s*[•|]\s*", body) if x.strip()]
    if len(items) < 3:
        items = [x.strip() for x in _sentences(body, 6) if x.strip()]
    if not items:
        items = [heading]
    tiles = []
    for idx, item in enumerate(items[:6]):
        tiles.append(
            f'''<div class="gallery-tile gallery-tile-{idx % 4} reveal">
              {_render_visual(item[:34], idx + 2, spec)}
              <span>{_e(item[:90])}</span>
            </div>'''
        )
    return f'''<section class="section gallery-section"><div class="shell">
      <div class="section-head reveal"><span class="label">{_e(_section_label(config, section.get('type') or 'Gallery', spec))}</span><h2>{_e(heading)}</h2></div>
      <div class="gallery-grid">{''.join(tiles)}</div>
    </div></section>'''


def _structured_items(value: Any, limit: int = 8) -> list[str]:
    raw = _text(value)
    if not raw:
        return []
    if "•" in raw:
        parts = re.split(r"\s*•\s*", raw)
    elif "→" in raw:
        parts = re.split(r"\s*→\s*", raw)
    else:
        parts = re.split(r"(?<=[.!?])\s+", raw)
    out = []
    for part in parts:
        item = re.sub(r"\s+", " ", part).strip(" -•→")
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _render_program_section(config: dict[str, Any], section: dict[str, Any], spec: dict[str, Any]) -> str:
    heading = _text(section.get("heading"), "Programi" if _is_sl(config, spec) else "Programmes")
    items = _structured_items(section.get("body"), 6)
    if len(items) < 2:
        return ""
    cards = []
    for index, item in enumerate(items):
        cards.append(
            f'<article class="program-card reveal"><span>0{index + 1}</span><h3>{_e(item)}</h3></article>'
        )
    return f'''<section class="section programme-section"><div class="shell">
      <div class="section-head reveal"><span class="label">{_e(_section_label(config, section.get("type") or "program-list", spec))}</span><h2>{_e(heading)}</h2></div>
      <div class="program-grid">{"".join(cards)}</div>
    </div></section>'''


def _render_process_section(config: dict[str, Any], section: dict[str, Any], spec: dict[str, Any]) -> str:
    heading = _text(section.get("heading"), "Proces" if _is_sl(config, spec) else "Process")
    items = _structured_items(section.get("body"), 7)
    if len(items) < 3:
        return ""
    steps = "".join(
        f'<div class="process-step reveal"><span>0{i}</span><strong>{_e(item)}</strong></div>'
        for i, item in enumerate(items, 1)
    )
    return f'''<section class="section process-section"><div class="shell">
      <div class="section-head reveal"><span class="label">{_e(_section_label(config, section.get("type") or "process", spec))}</span><h2>{_e(heading)}</h2></div>
      <div class="process-strip">{steps}</div>
    </div></section>'''


def _render_principles_section(config: dict[str, Any], section: dict[str, Any], spec: dict[str, Any]) -> str:
    heading = _text(section.get("heading"), "Pristop" if _is_sl(config, spec) else "Approach")
    items = _structured_items(section.get("body"), 6)
    if len(items) < 2:
        return ""
    blocks = "".join(
        f'<article class="principle-card reveal"><span>{i:02d}</span><p>{_e(item)}</p></article>'
        for i, item in enumerate(items, 1)
    )
    return f'''<section class="section principles-section"><div class="shell">
      <div class="section-head reveal"><span class="label">{_e(_section_label(config, section.get("type") or "principles", spec))}</span><h2>{_e(heading)}</h2></div>
      <div class="principles-grid">{blocks}</div>
    </div></section>'''


def _render_story_section(config: dict[str, Any], section: dict[str, Any], spec: dict[str, Any]) -> str:
    heading = _text(section.get("heading"), "Zgodba" if _is_sl(config, spec) else "Story")
    body = _text(section.get("body"))
    paras = _sentences(body, 5) or [body]
    body_html = "".join(f"<p>{_e(p)}</p>" for p in paras if p)
    return f'''<section class="section story-editorial"><div class="shell story-editorial-grid">
      <div class="section-head reveal"><span class="label">{_e(_section_label(config, section.get("type") or "story", spec))}</span><h2>{_e(heading)}</h2></div>
      <div class="story-editorial-copy reveal">{body_html}</div>
    </div></section>'''


def _hero_lead(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any]) -> str:
    """Create a page lead that never duplicates the first content paragraph."""
    if str(page.get("slug") or "") == "index":
        return _text(config.get("hero_subtitle"), _text(config.get("goal")))

    sl = _is_sl(config, spec)
    kind = _page_kind(page)
    role_copy = {
        "programs": (
            "Izberi program glede na izkušnje, velikost skupine in cilj."
            if sl else "Choose a programme around experience, group size and the outcome you want."
        ),
        "approach": (
            "Praktičen proces od opazovanja in razumevanja do samostojne uporabe."
            if sl else "A practical path from observation and understanding to independent use."
        ),
        "about": (
            "Kaj stoji za studiem, kako delamo in kaj je v središču našega pristopa."
            if sl else "What sits behind the studio, how we work and what guides the approach."
        ),
        "gallery": (
            "Teren, delo in detajli, ki pokažejo značaj programa brez generičnih podob."
            if sl else "Fieldwork, process and details that show the character of the programme without generic imagery."
        ),
        "contact": (
            "Povej nam, kaj želiš organizirati, in pošlji osnovne informacije za naslednji korak."
            if sl else "Tell us what you want to organise and share the essentials for the next step."
        ),
        "content": (
            "Vsebina te strani izhaja neposredno iz briefa projekta."
            if sl else "This page is built directly from the project brief."
        ),
    }

    sections = [s for s in (page.get("sections") or []) if isinstance(s, dict)]
    bodies = {base._fold_text(_text(s.get("body"))) for s in sections if _text(s.get("body"))}
    meta = _text(page.get("meta_description"))
    purpose = _text(page.get("purpose"))
    for candidate in (meta, purpose):
        folded = base._fold_text(candidate)
        if not candidate or folded in bodies:
            continue
        if any(folded.startswith(base._fold_text(prefix)) for prefix in (
            "predstaviti ", "razloziti ", "vizualno prikazati ", "preprost ", "mocan prvi vtis",
            "show ", "explain ", "present ",
        )):
            continue
        return candidate
    return role_copy.get(kind, role_copy["content"])


def _render_content_sections(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any]) -> str:
    out: list[str] = []
    sections = [s for s in (page.get("sections") or []) if isinstance(s, dict)]
    filtered = [s for s in sections if str(s.get("type") or "").lower() not in {"hero", "cta"}]
    seen_headings: set[str] = set()
    slug = str(page.get("slug") or "index")
    if not filtered:
        contexts = base._extract_page_contexts(config)
        filtered = base._grounded_sections(page, contexts.get(slug, ""), config)

    for idx, section in enumerate(filtered[:4]):
        kind = base._fold_text(section.get("type"))
        if "gallery" in kind:
            out.append(_render_gallery_section(config, section, page, spec))
            continue
        if kind in {"program list", "programs", "services", "service list"}:
            rendered = _render_program_section(config, section, spec)
            if rendered:
                out.append(rendered)
                continue
        if kind in {"process", "journey", "steps"}:
            rendered = _render_process_section(config, section, spec)
            if rendered:
                out.append(rendered)
                continue
        if kind in {"principles", "key points", "highlights", "audience"}:
            rendered = _render_principles_section(config, section, spec)
            if rendered:
                out.append(rendered)
                continue
        if kind in {"story", "trust"}:
            out.append(_render_story_section(config, section, spec))
            continue

        raw_heading = _text(section.get("heading"), page.get("title") or "Overview")
        normalized = base._fold_text(raw_heading)
        if normalized in seen_headings:
            # Do not expose mechanical "— Text" suffixes. A duplicate heading is
            # better represented by the section's purpose.
            qualifier = _text(section.get("type"), f"Part {idx + 1}").replace("_", " ").strip()
            raw_heading = qualifier.title() if qualifier else f"{page.get('title')} {idx + 1}"
            normalized = base._fold_text(raw_heading)
        seen_headings.add(normalized)

        heading = _e(raw_heading)
        body = _text(section.get("body"), page.get("purpose") or "")
        # Bulleted brief facts stay visually scannable instead of becoming one
        # repeated marketing paragraph.
        bullets = [x.strip() for x in re.split(r"\s*•\s*", body) if x.strip()]
        if len(bullets) >= 3:
            body_html = "<ul class=\"fact-list\">" + "".join(f"<li>{_e(x)}</li>" for x in bullets[:8]) + "</ul>"
        else:
            paras = _sentences(body, 4) or [body]
            body_html = "".join(f"<p>{_e(p)}</p>" for p in paras if p)

        layout_seed = int(hashlib.sha256(f"{slug}|{raw_heading}|{idx}".encode("utf-8")).hexdigest()[:4], 16)
        variants = (
            "section-split",
            "section-split section-split-reverse",
            "section-stack",
            "section-rail",
        )
        variant = variants[layout_seed % len(variants)]
        out.append(f'''<section class="section content-section content-{idx + 1}"><div class="shell {variant}">
          <div class="section-head reveal"><span class="label">{_e(_section_label(config, section.get('type') or 'Overview', spec))}</span><h2>{heading}</h2></div>
          <div class="prose reveal">{body_html}</div>
        </div></section>''')
    return "".join(out)


def _render_home_focus(config: dict[str, Any]) -> str:
    audience = _text(config.get("audience"), "People looking for a clear next step.")
    programme = _text(config.get("programme"), "Focused work")
    goal = _text(config.get("goal"), "Turn the brief into a clear, useful experience.")
    return f'''<section class="section home-focus"><div class="shell section-split">
      <div class="section-head reveal"><span class="label">Built around the brief</span><h2>{_e(programme)}</h2></div>
      <div class="prose reveal"><p>{_e(goal)}</p><p><strong>For:</strong> {_e(audience)}</p></div>
    </div></section>'''


def _render_metrics(config: dict[str, Any]) -> str:
    items = _metrics(config)
    if not items:
        return ""
    blocks = "".join(
        f'<div class="metric reveal"><strong>{_e(num)}</strong><span>{_e(label)}</span></div>'
        for num, label in items
    )
    return f'''<section class="section metric-band"><div class="shell">
      <div class="section-head reveal"><span class="label">At a glance</span><h2>Ambition made visible.</h2></div>
      <div class="metrics">{blocks}</div>
    </div></section>'''


def _render_journey(config: dict[str, Any]) -> str:
    steps = _journey(config)
    if not steps:
        return ""
    items = "".join(
        f'<div class="step reveal"><span>0{i}</span><h3>{_e(name)}</h3><div class="step-line"></div></div>'
        for i, name in enumerate(steps, 1)
    )
    return f'''<section class="section journey"><div class="shell">
      <div class="section-head reveal"><span class="label">Journey</span><h2>From first thought to real-world action.</h2></div>
      <div class="steps">{items}</div>
    </div></section>'''


def _render_contact(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any]) -> str:
    email = _text(config.get("contact_email"))
    sl = _is_sl(config, spec)
    title = "Pošlji povpraševanje." if sl else "Start a conversation."
    copy = (
        "Povej nam, kateri program te zanima, okvirno velikost skupine in kaj želiš doseči."
        if sl else
        "Tell us which programme you are interested in, the approximate group size and what you want to achieve."
    )
    email_html = (
        f'<a href="mailto:{_e(email, quote=True)}">{_e(email)}</a>'
        if email else
        f'<span>{"Uporabi spodnji obrazec." if sl else "Use the form below."}</span>'
    )
    fields = (
        ("Ime", "Email", "Program", "Število oseb", "Sporočilo")
        if sl else
        ("Name", "Email", "Programme", "Group size", "Message")
    )
    action = f'mailto:{_e(email, quote=True)}' if email else "#"
    return f'''<section class="section contact-panel"><div class="shell contact-grid">
      <div class="section-head reveal"><span class="label">{_e(_ui(config, "contact", spec))}</span><h2>{_e(title)}</h2><p>{_e(copy)}</p><div class="contact-box">{email_html}</div></div>
      <form class="contact-form reveal" action="{action}" method="post" enctype="text/plain">
        <label>{_e(fields[0])}<input name="name" autocomplete="name" required></label>
        <label>{_e(fields[1])}<input name="email" type="email" autocomplete="email" required></label>
        <label>{_e(fields[2])}<input name="programme"></label>
        <label>{_e(fields[3])}<input name="group_size" inputmode="numeric"></label>
        <label class="form-wide">{_e(fields[4])}<textarea name="message" rows="5" required></textarea></label>
        <button class="button button-accent form-wide" type="submit">{_e(config.get("cta_text") or ("Pošlji povpraševanje" if sl else "Send enquiry"))}<span>↗</span></button>
      </form>
    </div></section>'''

def _contact_href(spec: dict[str, Any]) -> str:
    pages = [p for p in (spec.get("pages") or []) if isinstance(p, dict)]
    preferred = ("contact", "kontakt", "stik", "contact-us", "kontakti")
    for wanted in preferred:
        for page in pages:
            slug = str(page.get("slug") or "").strip().lower()
            title = str(page.get("title") or "").strip().lower()
            if slug == wanted or title == wanted:
                return _href(str(page.get("slug") or "index"))
    for page in pages:
        slug = str(page.get("slug") or "").strip().lower()
        title = str(page.get("title") or "").strip().lower()
        if any(token in slug or token in title for token in ("contact", "kontakt", "stik")):
            return _href(str(page.get("slug") or "index"))
    return "index.html"


def _render_cta(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any]) -> str:
    if _page_kind(page) == "contact":
        return ""
    label = _text(config.get("cta_text"), "Kontaktirajte nas" if _is_sl(config, spec) else "Contact us")
    page_title = _text(page.get("title"), "")
    if _is_sl(config, spec):
        heading = f"Želiš narediti naslednji korak po strani »{page_title}«?" if page_title else "Želiš narediti naslednji korak?"
    else:
        heading = f"Ready for the next step after {page_title}?" if page_title else "Ready for the next step?"
    return f'''<section class="section final-cta"><div class="shell reveal">
      <span class="label">{_e(_ui(config, "next", spec))}</span><h2>{_e(heading)}</h2>
      <a class="button button-accent" href="{_e(_contact_href(spec), quote=True)}">{_e(label)}<span>↗</span></a>
    </div></section>'''

def _render_page(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any], index: int) -> str:
    slug = str(page.get("slug") or "index")
    is_home = slug == "index"
    site_name = _text(spec.get("site_name"), config.get("organization") or config.get("name") or "Website")
    page_title = _text(page.get("title"), "Home")
    meta = _text(page.get("meta_description"), page.get("purpose") or config.get("goal") or "")[:160]
    nav = _navigation(spec, slug)
    hero_title = _text(config.get("hero_title"), page_title) if is_home else page_title
    hero_body = _hero_lead(config, spec, page)
    programme = _text(config.get("programme"), "Project / digital experience")
    email = _text(config.get("contact_email"))
    sl = _is_sl(config, spec)
    language = "sl" if sl else (_text(config.get("language"), "en")[:8] or "en")
    mark = _brand_mark(site_name)
    cta_label = _text(config.get("cta_text"), "Poglej več" if sl else "Explore")
    cta_fold = base._fold_text(cta_label)

    primary_href = _contact_href(spec)
    if is_home and any(token in cta_fold for token in ("program", "storitev", "service", "ponud")):
        primary_href = _find_page_href(spec, ("program", "programme", "storitve", "services", "ponudba"), primary_href)

    body = [f'''<section class="hero {'hero-home' if is_home else 'hero-inner'}"><div class="shell hero-grid">
      <div class="hero-copy reveal"><span class="label label-light">{_e(programme)}</span><h1>{_e(hero_title)}</h1><p>{_e(hero_body)}</p>
      <div class="hero-actions"><a class="button button-accent" href="{_e(primary_href, quote=True)}">{_e(cta_label)}<span>↗</span></a><a class="text-link" href="#content">{_e(_ui(config, "discover", spec))}</a></div>
      </div><div class="hero-art reveal">{_render_visual(page_title, index, spec)}<div class="hero-note"><span>{_e(_ui(config, "project", spec))}</span><strong>{_e(site_name)}</strong></div></div>
    </div></section><div id="content"></div>''']

    # Page-specific model/brief content owns the narrative. Avoid inserting the
    # same generic "home focus / journey / metrics" blocks into every project.
    body.append(_render_content_sections(config, spec, page))

    # Real metrics are still useful when they were explicitly supplied.
    if is_home:
        body.append(_render_metrics(config))

    body.append(_render_crosslinks(config, spec, slug))
    if _page_kind(page) == "contact":
        body.append(_render_contact(config, spec, page))
    body.append(_render_cta(config, spec, page))

    contact_link = f'<a href="mailto:{_e(email, quote=True)}">{_e(email)}</a>' if email else ""
    footer_summary = programme if programme and programme != "Project / digital experience" else site_name
    no_contact = "Uporabi kontaktno stran" if sl else "Use the contact page"

    return f'''<!doctype html>
<html lang="{_e(language, quote=True)}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(page_title)} | {_e(site_name)}</title><meta name="description" content="{_e(meta, quote=True)}">
<meta property="og:title" content="{_e(page_title, quote=True)} | {_e(site_name, quote=True)}"><meta property="og:description" content="{_e(meta, quote=True)}"><meta property="og:type" content="website">
<meta name="theme-color" content="{_configured_brand(config)['primary']}"><link rel="stylesheet" href="assets/site.css">
</head>
<body class="page page-{_e(slug, quote=True)} page-kind-{_page_kind(page)}"><a class="skip" href="#content">{_e(_ui(config, "skip", spec))}</a>
<header class="site-header"><div class="shell nav"><a class="brand" href="index.html"><span class="brand-mark">{_e(mark)}</span><span>{_e(site_name)}</span></a><button class="menu" type="button" aria-label="{_e(_ui(config, "menu", spec), quote=True)}" aria-expanded="false" aria-controls="navLinks"><span></span><span></span></button><nav id="navLinks" class="nav-links" aria-label="{_e(_ui(config, "primary_nav", spec), quote=True)}">{nav}</nav></div></header>
<main>{''.join(body)}</main>
<footer class="site-footer"><div class="shell footer-grid"><div><a class="brand brand-footer" href="index.html"><span class="brand-mark">{_e(mark)}</span><span>{_e(site_name)}</span></a><p>{_e(footer_summary)}</p></div><div><span class="footer-label">{_e(_ui(config, "navigate", spec))}</span><nav class="footer-nav" aria-label="{_e(_ui(config, "footer_nav", spec), quote=True)}">{nav}</nav></div><div><span class="footer-label">{_e(_ui(config, "contact", spec))}</span>{contact_link or f'<span>{_e(no_contact)}</span>'}</div></div><div class="shell footer-bottom"><span>© {_e(site_name)}</span><span>{_e(_ui(config, "footer_note", spec))}</span></div></footer>
<script src="assets/site.js" defer></script></body></html>'''

def _css(config: dict[str, Any]) -> str:
    b = _configured_brand(config)
    return f''':root{{--primary:{b['primary']};--accent:{b['accent']};--accent-readable:{b['accent_readable']};--accent-ink:{b['accent_ink']};--bg:{b['background']};--ink:{b['text']};--paper:#fff;--muted:#667770;--dark:#071d18;--dark2:#0d2b24;--line:rgba(16,33,43,.14);--shell:1240px;--radius:28px}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;max-width:100%;overflow-x:hidden}}body{{margin:0;max-width:100%;overflow-x:hidden;background:var(--bg);color:var(--ink);font:400 16px/1.6 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}}a{{color:inherit}}img{{max-width:100%;height:auto}}.shell{{width:min(var(--shell),calc(100% - 48px));margin:auto;min-width:0}}.skip{{position:fixed;left:16px;top:-80px;z-index:1000;background:var(--accent);color:var(--accent-ink);padding:12px 16px;border-radius:999px;font-weight:800}}.skip:focus{{top:16px}}a:focus-visible,button:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}
.site-header{{position:fixed;inset:0 0 auto;z-index:100;border-bottom:1px solid rgba(255,255,255,.12);background:rgba(7,29,24,.82);backdrop-filter:blur(18px)}}.nav{{min-height:82px;display:flex;align-items:center;gap:28px}}.brand{{display:flex;align-items:center;gap:10px;color:#fff;font-weight:850;text-decoration:none;letter-spacing:-.025em}}.brand-mark{{width:32px;height:32px;display:grid;place-items:center;border-radius:10px;background:var(--accent);color:var(--accent-ink);font-size:13px;font-weight:950}}.nav-links{{margin-left:auto;display:flex;align-items:center;gap:26px}}.nav-links a{{position:relative;color:#dce9e5;text-decoration:none;font-size:14px;font-weight:650}}.nav-links a::after{{content:"";position:absolute;left:0;right:100%;bottom:-7px;height:2px;background:var(--accent);transition:.25s}}.nav-links a:hover::after,.nav-links a[aria-current="page"]::after{{right:0}}.menu{{display:none;margin-left:auto;width:44px;height:44px;border:1px solid rgba(255,255,255,.18);border-radius:14px;background:transparent}}.menu span{{display:block;width:18px;height:2px;margin:5px auto;background:#fff}}
.hero{{position:relative;overflow:hidden;background-color:var(--dark);background-image:linear-gradient(135deg,var(--dark) 0%,var(--primary) 68%,var(--dark2) 100%);color:#fff}}.hero::after{{content:"";position:absolute;right:-12vw;top:-18vw;width:45vw;height:45vw;border:1px solid rgba(199,255,74,.18);border-radius:50%;box-shadow:0 0 0 80px rgba(199,255,74,.035),0 0 0 160px rgba(199,255,74,.02)}}.hero-grid{{position:relative;z-index:2;min-height:760px;padding:150px 0 84px;display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);align-items:center;gap:72px}}.hero-inner .hero-grid{{min-height:620px}}.hero-copy h1{{max-width:940px;margin:18px 0 26px;font-size:clamp(58px,7.4vw,118px);line-height:.88;letter-spacing:-.075em;font-weight:900;text-wrap:balance;overflow-wrap:anywhere}}.hero-inner .hero-copy h1{{font-size:clamp(54px,6vw,92px)}}.hero-copy p{{max-width:720px;margin:0;color:#c7d7d2;font-size:clamp(18px,1.7vw,24px);line-height:1.5}}.label{{display:inline-flex;align-items:center;gap:9px;font-size:12px;font-weight:850;letter-spacing:.12em;text-transform:uppercase;color:var(--primary)}}.label::before{{content:"";width:22px;height:2px;background:currentColor}}.label-light{{color:var(--accent-readable)}}.hero-actions{{display:flex;align-items:center;gap:24px;margin-top:38px;flex-wrap:wrap}}.button{{display:inline-flex;align-items:center;justify-content:center;gap:14px;min-height:54px;padding:0 22px;border-radius:999px;text-decoration:none;font-weight:800;transition:transform .25s,box-shadow .25s}}.button:hover{{transform:translateY(-3px)}}.button-accent{{background:var(--accent);color:var(--accent-ink);box-shadow:0 14px 40px rgba(199,255,74,.12)}}.button span{{font-size:18px}}.text-link{{color:#e6f0ed;text-underline-offset:5px;font-weight:650}}
.hero-art{{position:relative;min-height:460px}}.visual{{position:relative;min-height:440px;height:100%;overflow:hidden;border-radius:var(--radius);background-color:#f8f5ec;background-image:linear-gradient(145deg,#f8f5ec 0%,#dce7df 100%);color:#071d18;box-shadow:0 42px 90px rgba(0,0,0,.28);isolation:isolate}}.visual-grid{{position:absolute;inset:0;background-image:linear-gradient(rgba(7,29,24,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(7,29,24,.08) 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(to bottom,#000,transparent)}}.visual-frame{{position:absolute;inset:12%;border:1px solid rgba(7,29,24,.2);border-radius:var(--radius);opacity:0}}.visual-axis{{position:absolute;left:10%;right:10%;top:18%;display:none;gap:9px;align-items:flex-end;height:42%}}.visual-axis i,.visual-bars i{{display:block;background:var(--primary)}}.visual-axis i:nth-child(1){{width:8%;height:42%}}.visual-axis i:nth-child(2){{width:8%;height:78%}}.visual-axis i:nth-child(3){{width:8%;height:100%}}.visual-bars{{position:absolute;inset:15%;display:none;grid-template-columns:repeat(2,1fr);gap:12px}}.visual-bars i{{border-radius:12px;opacity:.82}}.visual-bars i:nth-child(2){{background:var(--accent)}}.visual-bars i:nth-child(3){{background:#fff;border:1px solid rgba(7,29,24,.18)}}.visual-bars i:nth-child(4){{background:color-mix(in srgb,var(--primary) 35%,#fff)}}.visual-orb{{position:absolute;border-radius:50%;filter:blur(.2px)}}.visual-orb-a{{width:240px;height:240px;right:-35px;top:42px;background:var(--accent);box-shadow:0 0 0 26px rgba(199,255,74,.18)}}.visual-orb-b{{width:150px;height:150px;left:54px;bottom:42px;background:var(--primary);opacity:.88}}.visual strong{{position:absolute;left:34px;bottom:34px;z-index:3;max-width:70%;font-size:clamp(30px,3vw,52px);line-height:.95;letter-spacing:-.055em;text-wrap:balance;overflow-wrap:anywhere}}.visual-kicker{{position:absolute;left:34px;top:28px;z-index:3;font-size:13px;font-weight:900}}.visual-chip{{position:absolute;right:24px;top:22px;z-index:4;padding:7px 10px;border:1px solid rgba(7,29,24,.18);border-radius:999px;background:rgba(255,255,255,.7);backdrop-filter:blur(8px);font-size:9px;font-weight:850;letter-spacing:.08em;text-transform:uppercase}}.visual-arrow{{position:absolute;right:30px;bottom:26px;z-index:3;font-size:32px}}.visual-v0 .visual-frame{{opacity:1;inset:9% 10% 26% 10%}}.visual-v0 .visual-orb-a{{width:110px;height:110px;right:12%;top:18%;box-shadow:0 0 0 18px rgba(199,255,74,.14)}}.visual-v0 .visual-orb-b{{display:none}}.visual-v1 .visual-orb-a{{width:290px;height:290px;right:-60px;top:-35px}}.visual-v1 .visual-orb-b{{width:180px;height:180px;left:12%;bottom:10%}}.visual-v1 .visual-frame{{opacity:.5;inset:18% 8% 12% 28%;border-radius:50%}}.visual-v2 .visual-orb{{display:none}}.visual-v2 .visual-grid{{background-size:32px 32px}}.visual-v2 .visual-axis{{display:flex}}.visual-v2 strong{{max-width:55%;bottom:28px}}.visual-v3{{background:var(--accent)}}.visual-v3 .visual-grid,.visual-v3 .visual-orb-b{{display:none}}.visual-v3 .visual-orb-a{{width:62%;height:120%;right:-18%;top:-10%;background:var(--primary);border-radius:0;transform:rotate(16deg);box-shadow:none}}.visual-v3 strong{{font-size:clamp(42px,5vw,78px);max-width:78%;text-transform:uppercase}}.visual-v4 .visual-orb{{border-radius:0;filter:none}}.visual-v4 .visual-orb-a{{width:54%;height:120%;right:-12%;top:-10%;transform:rotate(12deg);box-shadow:none}}.visual-v4 .visual-orb-b{{width:42%;height:110%;left:-14%;bottom:-15%;transform:rotate(-12deg);opacity:.28}}.visual-v4 .visual-frame{{opacity:.55;inset:13%}}.visual-v5 .visual-grid,.visual-v5 .visual-orb{{display:none}}.visual-v5 .visual-bars{{display:grid;transform:rotate(-4deg)}}.visual-v5 .visual-bars i{{box-shadow:0 18px 40px rgba(0,0,0,.12)}}.visual-v6 .visual-orb{{display:none}}.visual-v6 .visual-bars{{display:grid;inset:10%;grid-template-columns:1.4fr .8fr;grid-template-rows:.8fr 1.2fr}}.visual-v6 .visual-bars i{{border-radius:0}}.visual-v6 strong{{left:50%;bottom:30px;max-width:44%}}.visual-v7{{background:#071d18;color:#fff}}.visual-v7 .visual-grid{{opacity:.25}}.visual-v7 .visual-orb-a{{width:180px;height:180px;right:10%;top:18%;box-shadow:0 0 0 1px var(--accent),0 0 0 34px rgba(199,255,74,.07);background:transparent;border:18px solid var(--accent)}}.visual-v7 .visual-orb-b{{width:2px;height:54%;left:24%;bottom:18%;border-radius:0;background:var(--accent)}}.visual-v7 .visual-chip{{color:#fff;background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.16)}}.hero-note{{position:absolute;right:-18px;bottom:-18px;z-index:4;width:190px;padding:18px 20px;border-radius:20px;background:#fff;color:var(--ink);box-shadow:0 22px 50px rgba(0,0,0,.22)}}.hero-note span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em}}.hero-note strong{{display:block;margin-top:4px;line-height:1.15}}
.hero-grid>*,.intro-grid>*,.section-split>*,.section-stack>*,.section-rail>*,.contact-grid>*,.story-grid>*,.footer-grid>*,.gallery-grid>*{{min-width:0}}.brand,.brand span,.nav-links a,.footer-grid a,.section-head h2,.story-card h3,.final-cta h2{{overflow-wrap:anywhere}}.section{{padding:112px 0}}.section:nth-of-type(even):not(.hero):not(.section-ink):not(.metric-band):not(.final-cta){{background:rgba(255,255,255,.42)}}.section-head h2{{max-width:820px;margin:16px 0 0;font-size:clamp(42px,5.4vw,78px);line-height:.98;letter-spacing:-.06em;text-wrap:balance}}.section-head>p{{max-width:620px;color:var(--muted);font-size:18px}}.intro-grid,.section-split{{display:grid;grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:clamp(60px,9vw,140px);align-items:start}}.section-split-reverse{{grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr)}}.section-split-reverse .section-head{{order:2}}.prose{{max-width:720px;padding-top:10px}}.prose p{{margin:0 0 22px;font-size:clamp(18px,1.6vw,22px);line-height:1.65;color:#42564f}}.prose p:first-child{{font-size:clamp(24px,2.4vw,34px);line-height:1.4;color:var(--ink);letter-spacing:-.025em}}.section-stack{{display:grid;gap:34px}}.section-stack .section-head{{max-width:980px}}.section-stack .prose{{max-width:900px;padding-top:0}}.section-rail{{display:grid;grid-template-columns:minmax(220px,.55fr) minmax(0,1.45fr);gap:clamp(44px,8vw,120px);align-items:start;border-left:3px solid var(--accent);padding-left:clamp(22px,3vw,44px)}}.fact-list{{display:grid;gap:12px;margin:0;padding:0;list-style:none}}.fact-list li{{padding:15px 18px;border-left:3px solid var(--accent);background:rgba(255,255,255,.58);font-size:17px}}.program-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:48px}}.program-card{{min-height:210px;padding:28px;border:1px solid var(--line);border-radius:var(--radius);background:var(--paper)}}.program-card>span,.principle-card>span,.process-step>span{{display:block;color:var(--muted);font-size:11px;font-weight:850;letter-spacing:.12em}}.program-card h3{{max-width:18ch;margin:58px 0 0;font-size:clamp(26px,3vw,42px);line-height:1;letter-spacing:-.045em}}
.process-strip{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin-top:52px;border-top:1px solid var(--line)}}.process-step{{position:relative;min-height:180px;padding:24px 22px 22px 0;border-right:1px solid var(--line)}}.process-step:last-child{{border-right:0}}.process-step strong{{display:block;margin-top:48px;font-size:clamp(19px,2vw,30px);line-height:1.1;letter-spacing:-.035em}}
.principles-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:48px}}.principle-card{{min-height:220px;padding:26px;border-radius:var(--radius);background:var(--paper);border:1px solid var(--line)}}.principle-card p{{margin:56px 0 0;font-size:clamp(18px,1.7vw,24px);line-height:1.35;color:var(--ink)}}
.story-editorial-grid{{display:grid;grid-template-columns:minmax(0,.7fr) minmax(0,1.3fr);gap:clamp(60px,10vw,150px);align-items:start}}.story-editorial-copy{{max-width:760px}}.story-editorial-copy p{{margin:0 0 24px;font-size:clamp(20px,2vw,30px);line-height:1.5;color:var(--ink)}}.story-editorial-copy p+ p{{font-size:18px;color:var(--muted)}}
.gallery-section{{overflow:hidden}}.gallery-grid{{display:grid;grid-template-columns:1.2fr .8fr 1fr;grid-auto-rows:minmax(240px,1fr);gap:14px;margin-top:48px}}.gallery-tile{{position:relative;min-height:260px;overflow:hidden;border-radius:var(--radius);background:#fff;border:1px solid var(--line)}}.gallery-tile .visual{{height:100%;min-height:260px;border-radius:0;box-shadow:none}}.gallery-tile>span{{position:absolute;left:18px;right:18px;bottom:16px;z-index:6;padding:9px 11px;border-radius:10px;background:rgba(6,25,20,.84);color:#fff;font-size:12px;font-weight:750;backdrop-filter:blur(8px)}}.gallery-tile-0{{grid-row:span 2}}.gallery-tile-3{{grid-column:span 2}}
.journey{{background:#fff}}.steps{{display:grid;grid-template-columns:repeat(4,1fr);margin-top:60px;border-top:1px solid var(--line)}}.step{{position:relative;padding:30px 26px 18px 0;min-height:180px;border-right:1px solid var(--line)}}.step:last-child{{border-right:0}}.step>span{{font-size:12px;color:var(--muted);font-weight:800}}.step h3{{margin:36px 0 0;font-size:clamp(26px,2.5vw,40px);letter-spacing:-.04em}}.step-line{{position:absolute;left:0;top:-2px;width:48%;height:3px;background:var(--accent)}}
.metric-band{{background:var(--accent);color:#071d18}}.metric-band .label{{color:#071d18}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);margin-top:54px;border-top:1px solid rgba(7,29,24,.24)}}.metric{{padding:28px 20px 10px 0;border-right:1px solid rgba(7,29,24,.24)}}.metric:last-child{{border-right:0}}.metric strong{{display:block;font-size:clamp(46px,6vw,86px);line-height:1;letter-spacing:-.065em}}.metric span{{display:block;margin-top:10px;font-weight:700}}
.section-ink{{background:var(--dark);color:#fff}}.section-ink .label{{color:var(--accent-readable)}}.story-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:54px}}.story-card{{display:flex;min-height:560px;flex-direction:column;border:1px solid rgba(255,255,255,.12);border-radius:var(--radius);overflow:hidden;background:#0b2620;color:#fff;text-decoration:none;transition:transform .3s,border-color .3s}}.story-card:hover{{transform:translateY(-6px);border-color:rgba(199,255,74,.6)}}.story-card .visual{{min-height:270px;height:270px;border-radius:0;box-shadow:none}}.story-card-copy{{padding:26px}}.story-card-copy>span{{color:var(--accent-readable);font-size:11px;text-transform:uppercase;letter-spacing:.12em;font-weight:850}}.story-card h3{{margin:9px 0 12px;font-size:30px;line-height:1;letter-spacing:-.04em}}.story-card p{{margin:0;color:#aebfba}}.story-card b{{display:block;margin-top:auto;padding-top:22px;font-size:13px;color:var(--accent-readable)}}
.contact-panel{{background:#fff}}.contact-grid{{display:grid;grid-template-columns:minmax(0,.85fr) minmax(0,1.15fr);gap:80px;align-items:start}}.contact-box{{margin-top:28px;padding:28px;border-radius:var(--radius);background:var(--bg);border:1px solid var(--line)}}.contact-form{{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:28px;border-radius:var(--radius);background:var(--bg);border:1px solid var(--line)}}.contact-form label{{display:grid;gap:7px;color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}}.contact-form input,.contact-form textarea{{width:100%;border:1px solid rgba(16,33,43,.22);border-radius:12px;background:#fff;color:var(--ink);padding:14px 15px;font:inherit;text-transform:none;letter-spacing:0}}.contact-form textarea{{resize:vertical}}.contact-form input:focus,.contact-form textarea:focus{{outline:3px solid color-mix(in srgb,var(--accent) 45%,transparent);border-color:var(--primary)}}.form-wide{{grid-column:1/-1}}.contact-box>span{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.12em}}.contact-box>a{{display:block;margin-top:12px;font-size:clamp(26px,3vw,44px);line-height:1.1;letter-spacing:-.045em;font-weight:850;word-break:break-word}}.contact-box p{{color:var(--muted)}}.final-cta{{background-color:var(--dark);background-image:linear-gradient(135deg,var(--primary),var(--dark));color:#fff}}.final-cta .label{{color:var(--accent-readable)}}.final-cta h2{{max-width:900px;margin:18px 0 34px;font-size:clamp(50px,6vw,92px);line-height:.92;letter-spacing:-.065em}}
.site-footer{{padding:76px 0 28px;background:#061914;color:#d7e5e1}}.footer-grid{{display:grid;grid-template-columns:1.3fr .7fr .7fr;gap:60px;padding-bottom:58px}}.brand-footer{{margin-bottom:20px}}.footer-grid p{{max-width:430px;color:#829993}}.footer-label{{display:block;margin-bottom:16px;color:var(--accent-readable);font-size:11px;text-transform:uppercase;letter-spacing:.14em;font-weight:850}}.footer-nav{{display:grid;gap:8px}}.footer-nav a,.footer-grid a{{color:#d7e5e1;text-decoration:none}}.footer-bottom{{padding-top:22px;border-top:1px solid rgba(255,255,255,.12);display:flex;justify-content:space-between;gap:20px;color:#759089;font-size:12px}}
.js .reveal{{opacity:0;transform:translateY(18px);transition:opacity .65s ease,transform .65s ease}}.js .reveal.is-visible{{opacity:1;transform:none}}
@media(max-width:980px){{.hero-grid{{grid-template-columns:1fr;min-height:auto;padding-top:142px}}.hero-art{{min-height:360px}}.hero-note{{right:0;max-width:min(190px,calc(100% - 16px))}}.intro-grid,.section-split,.section-split-reverse,.section-rail,.contact-grid{{grid-template-columns:1fr;gap:42px}}.section-rail{{border-left:0;padding-left:0;border-top:3px solid var(--accent);padding-top:28px}}.gallery-grid{{grid-template-columns:1fr 1fr}}.program-grid,.principles-grid{{grid-template-columns:1fr 1fr}}.process-strip{{grid-template-columns:repeat(3,1fr)}}.story-editorial-grid{{grid-template-columns:1fr;gap:36px}}.gallery-tile-0,.gallery-tile-3{{grid-row:auto;grid-column:auto}}.section-split-reverse .section-head{{order:0}}.steps,.metrics{{grid-template-columns:repeat(2,1fr)}}.story-grid{{grid-template-columns:1fr 1fr}}.footer-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:760px){{.gallery-grid,.contact-form,.program-grid,.principles-grid{{grid-template-columns:1fr}}.process-strip{{grid-template-columns:1fr}}.process-step{{border-right:0;border-bottom:1px solid var(--line)}}.form-wide{{grid-column:auto}}.visual-chip{{right:14px;top:14px;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.visual strong{{left:24px;bottom:24px;max-width:74%}}.visual-v6 strong{{left:48%;max-width:48%}}.shell{{width:min(100% - 28px,var(--shell))}}.nav{{min-height:70px}}.menu{{display:block}}.nav-links{{display:none;position:absolute;left:14px;right:14px;top:76px;padding:18px;border-radius:20px;background:#08221c;box-shadow:0 25px 60px rgba(0,0,0,.3);flex-direction:column;align-items:stretch;gap:0}}.nav-links.open{{display:flex}}.nav-links a{{padding:12px}}.hero-grid{{padding:120px 0 62px;gap:42px}}.hero-copy h1{{font-size:clamp(48px,15vw,76px)}}.hero-art,.visual{{min-height:330px}}.hero-note{{right:12px;bottom:-12px}}.section{{padding:78px 0}}.section-head h2{{font-size:clamp(38px,11vw,56px)}}.steps,.metrics,.story-grid,.footer-grid{{grid-template-columns:1fr}}.step,.metric{{border-right:0;border-bottom:1px solid var(--line)}}.story-card{{min-height:0}}.footer-bottom{{flex-direction:column}}}}
@media(max-width:980px){{.menu{{display:block}}.nav-links{{display:none;position:absolute;left:24px;right:24px;top:86px;padding:18px;border-radius:20px;background:#08221c;box-shadow:0 25px 60px rgba(0,0,0,.3);flex-direction:column;align-items:stretch;gap:0}}.nav-links.open{{display:flex}}.nav-links a{{padding:12px}}.nav{{position:relative}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}*{{animation:none!important;transition:none!important}}.js .reveal{{opacity:1;transform:none}}}}'''


def _js() -> str:
    return """document.documentElement.classList.add('js');\nconst menu=document.querySelector('.menu'),nav=document.querySelector('.nav-links');if(menu&&nav){menu.addEventListener('click',()=>{const open=nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(open));});nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{nav.classList.remove('open');menu.setAttribute('aria-expanded','false');}));}\nconst io=('IntersectionObserver'in window)?new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-visible');io.unobserve(e.target);}}),{threshold:.12}):null;document.querySelectorAll('.reveal').forEach(el=>io?io.observe(el):el.classList.add('is-visible'));"""


async def design_site(config: dict[str, Any]) -> dict[str, Any]:
    spec = await base.design_site(config)
    # Preserve model planning while adding a deterministic visual variant marker.
    for idx, page in enumerate(spec.get("pages") or []):
        page["design_variant"] = ["editorial", "split", "bento", "feature"][idx % 4]
    return spec


async def build_files(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, str]:
    files: dict[str, str] = {"assets/site.css": _css(config), "assets/site.js": _js()}
    pages = spec.get("pages") or []
    if not pages:
        spec = await design_site(config)
        pages = spec.get("pages") or []
    for idx, page in enumerate(pages):
        slug = str(page.get("slug") or ("index" if idx == 0 else f"page-{idx+1}"))
        if idx == 0:
            slug = "index"
        files[_href(slug)] = _strip_language_marker(_render_page(config, spec, page, idx), "html")
    files["robots.txt"] = "User-agent: *\nAllow: /\n"
    return base._repair_deterministic_bundle(files)


# Premium renderer loads after robust_generation and replaces only planning/build.
# Existing QA/self-fix functions remain active.
core.design_site = design_site
core.build_files = build_files
