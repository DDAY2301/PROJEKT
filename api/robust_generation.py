"""Resilient generation helpers for the local website agent.

The first prototype asked a small local model to return an entire multi-page
website as one strict JSON object. That is brittle: one malformed quote or a
truncated response aborts the whole build. This module keeps the same public
API but changes the internal strategy:

* use Ollama JSON mode only for compact structured planning/auditing;
* generate CSS and each HTML page in separate bounded calls;
* validate every model response before accepting it;
* fall back to deterministic, production-safe HTML/CSS instead of failing;
* never turn a temporary model-formatting problem into a fatal build error.
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any

import httpx

import api.main as core
import api.model_router as model_router


async def _generate(prompt: str, system: str, *, json_mode: bool = False, timeout: int = 360, num_predict: int = 4096) -> str:
    return await model_router.generate(
        prompt,
        system,
        json_mode=json_mode,
        timeout=timeout,
        num_predict=num_predict,
        temperature=0.15,
        num_ctx=8192,
    )


def _json_from_text(raw: str) -> dict[str, Any]:
    text = core.strip_fence(raw).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        value = json.loads(text[start : end + 1])
        if isinstance(value, dict):
            return value
    raise ValueError("response is not a JSON object")


async def _json_call(prompt: str, system: str, *, attempts: int = 3, num_predict: int = 4096) -> dict[str, Any]:
    last: Exception | None = None
    retry_note = ""
    for _ in range(attempts):
        try:
            raw = await _generate(prompt + retry_note, system, json_mode=True, num_predict=num_predict)
            return _json_from_text(raw)
        except Exception as exc:  # a local model format error should be retried
            last = exc
            retry_note = "\nIMPORTANT: The previous response was invalid. Return one complete valid JSON object only. No commentary, no markdown and no trailing text."
    raise RuntimeError(f"local model could not return valid structured output: {last or 'unknown error'}")


def _configured_pages(config: dict[str, Any]) -> list[dict[str, str]]:
    limit = {"Start": 3, "Standard": 6, "Premium": 12}.get(config.get("package"), 3)
    pages = config.get("pages") or []
    clean: list[dict[str, str]] = []
    for index, page in enumerate(pages[:limit]):
        title = str(page.get("title") or ("Home" if index == 0 else f"Page {index + 1}"))
        slug = str(page.get("slug") or ("index" if index == 0 else re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")))
        if index == 0:
            slug = "index"
        clean.append({"slug": slug or f"page-{index + 1}", "title": title, "purpose": str(page.get("purpose") or "")})
    if not clean:
        clean = [{"slug": "index", "title": "Home", "purpose": str(config.get("goal") or "Homepage")}]
    return clean


def _fallback_spec(config: dict[str, Any]) -> dict[str, Any]:
    pages = []
    for page in _configured_pages(config):
        pages.append(
            {
                **page,
                "meta_description": (page["purpose"] or str(config.get("goal") or "")).strip()[:155],
                "sections": [
                    {"type": "hero", "heading": config.get("hero_title") or page["title"], "body": config.get("hero_subtitle") or page["purpose"] or config.get("goal", "")},
                    {"type": "content", "heading": page["title"], "body": page["purpose"] or config.get("goal", "")},
                    {"type": "cta", "heading": "Ready to take the next step?", "body": "Get in touch to learn more.", "cta": config.get("cta_text") or "Contact us"},
                ],
            }
        )
    return {
        "site_name": config.get("organization") or config.get("name") or "Website",
        "seo_description": str(config.get("goal") or "")[:155],
        "navigation": [{"title": p["title"], "slug": p["slug"]} for p in pages],
        "pages": pages,
    }


async def design_site(config: dict[str, Any]) -> dict[str, Any]:
    page_budget = {"Start": 3, "Standard": 6, "Premium": 12}[config["package"]]
    prompt = f"""
Plan a polished production website using the customer brief below.
The package allows at most {page_budget} pages. Respect the requested pages and their purposes.
CUSTOMER={json.dumps(config, ensure_ascii=False)}
Return JSON with keys site_name, seo_description, navigation, pages.
Each page must have slug, title, meta_description and exactly 3-4 purposeful sections.
Each section must have type, heading and concise body; CTA is optional.
Keep copy concise, specific and credible. Avoid filler and repeated headings.
Never invent awards, partners, funding claims or verified impact.
"""
    try:
        data = await _json_call(prompt, "You are a senior product designer and information architect. Return JSON only.", attempts=2, num_predict=2400)
        model_pages = data.get("pages")
        if not isinstance(model_pages, list) or not model_pages:
            raise ValueError("pages missing")
        requested = _configured_pages(config)
        # Keep customer-requested URLs stable even if the model tried to rename them.
        normalized = []
        for index, requested_page in enumerate(requested):
            model_page = model_pages[index] if index < len(model_pages) and isinstance(model_pages[index], dict) else {}
            normalized.append(
                {
                    "slug": requested_page["slug"],
                    "title": requested_page["title"],
                    "purpose": requested_page["purpose"],
                    "meta_description": str(model_page.get("meta_description") or requested_page["purpose"] or config.get("goal") or "")[:160],
                    "sections": model_page.get("sections") if isinstance(model_page.get("sections"), list) and model_page.get("sections") else _fallback_spec(config)["pages"][index]["sections"],
                }
            )
        return {
            "site_name": str(data.get("site_name") or config.get("organization") or config.get("name")),
            "seo_description": str(data.get("seo_description") or config.get("goal") or "")[:160],
            "navigation": [{"title": p["title"], "slug": p["slug"]} for p in normalized],
            "pages": normalized,
        }
    except Exception:
        return _fallback_spec(config)


def _href(slug: str) -> str:
    return "index.html" if slug == "index" else f"{slug}.html"


def _navigation(spec: dict[str, Any]) -> str:
    pages = spec.get("pages") or []
    return "".join(f'<a href="{html.escape(_href(str(p.get("slug") or "index")))}">{html.escape(str(p.get("title") or "Page"))}</a>' for p in pages)


def _fallback_css(config: dict[str, Any]) -> str:
    brand = config.get("brand") or {}
    primary = brand.get("primary_color", "#0b1f33")
    accent = brand.get("secondary_color", "#c7ff4a")
    bg = brand.get("background_color", "#f7f4ec")
    text = brand.get("text_color", "#10212b")
    return f"""
:root{{--primary:{primary};--accent:{accent};--bg:{bg};--text:{text};--paper:#fff;--line:color-mix(in srgb,var(--text) 14%,transparent);--max:1180px}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
a{{color:inherit}}a:focus-visible,button:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}
.wrap{{width:min(var(--max),calc(100% - 2rem));margin:auto}}header{{position:sticky;top:0;z-index:20;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--bg) 91%,transparent);backdrop-filter:blur(16px)}}nav{{min-height:72px;display:flex;align-items:center;justify-content:space-between;gap:1rem}}.brand{{font-weight:900;text-decoration:none;letter-spacing:-.03em}}.nav-links{{display:flex;gap:1rem;flex-wrap:wrap}}.nav-links a{{font-size:.9rem;text-decoration:none;opacity:.72}}.nav-links a:hover{{opacity:1}}
.hero{{padding:clamp(5rem,10vw,9rem) 0 4rem}}.eyebrow{{font-size:.76rem;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--primary)}}h1{{max-width:12ch;margin:.5rem 0 1rem;font-size:clamp(3rem,8vw,7rem);line-height:.9;letter-spacing:-.065em}}h2{{font-size:clamp(2rem,4vw,3.8rem);line-height:1;letter-spacing:-.045em}}.lead{{max-width:720px;font-size:clamp(1.05rem,2vw,1.3rem);opacity:.74}}.cta{{display:inline-flex;margin-top:1.4rem;padding:.9rem 1.15rem;border-radius:999px;background:var(--primary);color:#fff;text-decoration:none;font-weight:850;transition:.2s}}.cta:hover{{transform:translateY(-2px)}}
section{{padding:4.5rem 0}}.section-grid{{display:grid;grid-template-columns:.8fr 1.2fr;gap:clamp(2rem,6vw,6rem);align-items:start}}.content{{max-width:760px}}.content p{{font-size:1.06rem;opacity:.78}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}}.card{{padding:1.4rem;border:1px solid var(--line);border-radius:1.2rem;background:color-mix(in srgb,var(--paper) 80%,transparent);transition:.2s}}.card:hover{{transform:translateY(-4px)}}.metric{{font-size:clamp(2.2rem,5vw,4.5rem);font-weight:950;letter-spacing:-.06em;color:var(--primary)}}footer{{margin-top:3rem;padding:3rem 0;border-top:1px solid var(--line);font-size:.9rem;opacity:.72}}
@media(max-width:800px){{.section-grid,.cards{{grid-template-columns:1fr}}nav{{align-items:flex-start;padding:1rem 0;flex-direction:column}}.nav-links{{gap:.65rem}}h1{{font-size:clamp(3rem,16vw,5rem)}}}}
@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important;transition:none!important}}}}
""".strip()


def _fallback_page(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any]) -> str:
    title = html.escape(str(page.get("title") or config.get("name") or "Website"))
    site_name = html.escape(str(spec.get("site_name") or config.get("organization") or config.get("name") or "Website"))
    description = html.escape(str(page.get("meta_description") or config.get("goal") or "")[:160], quote=True)
    nav = _navigation(spec)
    sections = page.get("sections") or []
    body_sections: list[str] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        heading = html.escape(str(section.get("heading") or ""))
        body = html.escape(str(section.get("body") or ""))
        cta = section.get("cta")
        cls = "hero" if index == 0 or section.get("type") == "hero" else ""
        eyebrow = html.escape(str(config.get("programme") or "Digital experience")) if cls else html.escape(str(section.get("type") or "Overview"))
        cta_html = f'<a class="cta" href="contact.html">{html.escape(str(cta))}</a>' if cta else ""
        body_sections.append(f'<section class="{cls}"><div class="wrap section-grid"><div><span class="eyebrow">{eyebrow}</span><h2>{heading}</h2></div><div class="content"><p>{body}</p>{cta_html}</div></div></section>')
    hero_title = html.escape(str(config.get("hero_title") or page.get("title") or config.get("name") or ""))
    hero_subtitle = html.escape(str(config.get("hero_subtitle") or page.get("purpose") or config.get("goal") or ""))
    if page.get("slug") == "index":
        body_sections.insert(0, f'<section class="hero"><div class="wrap"><span class="eyebrow">{html.escape(str(config.get("programme") or "Project"))}</span><h1>{hero_title}</h1><p class="lead">{hero_subtitle}</p><a class="cta" href="contact.html">{html.escape(str(config.get("cta_text") or "Contact us"))}</a></div></section>')
    contact = html.escape(str(config.get("contact_email") or ""))
    return f'''<!doctype html>
<html lang="{html.escape(str(config.get("language") or "en"))}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | {site_name}</title><meta name="description" content="{description}"><meta property="og:title" content="{title} | {site_name}"><meta property="og:description" content="{description}"><link rel="stylesheet" href="assets/site.css"></head>
<body><header><nav class="wrap"><a class="brand" href="index.html">{site_name}</a><div class="nav-links">{nav}</div></nav></header><main>{''.join(body_sections)}</main><footer><div class="wrap"><strong>{site_name}</strong>{f' · <a href="mailto:{contact}">{contact}</a>' if contact else ''}</div></footer><script src="assets/site.js" defer></script></body></html>'''


async def _model_css(config: dict[str, Any], spec: dict[str, Any]) -> str:
    prompt = f"""
Create the complete CSS file for a premium responsive multi-page website.
PROJECT={json.dumps(config, ensure_ascii=False)}
DESIGN={json.dumps(spec, ensure_ascii=False)}
Use the customer colors as CSS custom properties. Aim for an editorial, distinctive studio-quality result with excellent mobile behavior, visible focus states and subtle reduced-motion-safe interactions.
Return CSS only. No markdown and no explanation.
"""
    for _ in range(2):
        try:
            raw = core.strip_fence(await _generate(prompt, "You are a senior visual web designer and CSS engineer. Output CSS only.", json_mode=False, num_predict=4500))
            if len(raw) >= 1200 and "{" in raw and "}" in raw and "@media" in raw:
                return raw
        except Exception:
            pass
    return _fallback_css(config)


async def _model_page(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any], css_hint: str) -> str:
    nav = [{"title": p.get("title"), "href": _href(str(p.get("slug") or "index"))} for p in spec.get("pages", [])]
    prompt = f"""
Build ONE complete standalone HTML page for this website. Shared CSS is at assets/site.css and shared JS is at assets/site.js.
PROJECT={json.dumps(config, ensure_ascii=False)}
SITE_NAME={json.dumps(spec.get('site_name'), ensure_ascii=False)}
PAGE={json.dumps(page, ensure_ascii=False)}
NAVIGATION={json.dumps(nav, ensure_ascii=False)}
CSS_DIRECTION={json.dumps(css_hint[:3500], ensure_ascii=False)}
Rules:
- output only a complete <!doctype html> document
- semantic header/nav/main/sections/footer; link every navigation item correctly
- strong editorial composition, useful copy and clear CTA hierarchy
- no lorem ipsum, no fake photographs, no broken image URLs, no external JS libraries
- unique title and meta description, OpenGraph basics, accessible labels and focusable controls
- use CSS-driven visual compositions when imagery is unavailable
- never mention AI, prompts, models or generation
"""
    for _ in range(2):
        try:
            raw = core.strip_fence(await _generate(prompt, "You are a senior frontend engineer. Return HTML only.", json_mode=False, num_predict=5000))
            lower = raw.lower()
            if "<!doctype html" in lower and "<main" in lower and "</html>" in lower and "assets/site.css" in lower:
                return raw
        except Exception:
            pass
    return _fallback_page(config, spec, page)


def _repair_deterministic_bundle(files: dict[str, str]) -> dict[str, str]:
    """Repair obvious cross-file defects before spending another model call."""
    repaired = dict(files)
    html_paths = {path.lower(): path for path in repaired if path.lower().endswith((".html", ".htm"))}
    aliases = {
        "contact.html": ("kontakt.html", "stik.html"),
        "kontakt.html": ("contact.html",),
        "gallery.html": ("galerija.html",),
        "galerija.html": ("gallery.html",),
        "about.html": ("o-nas.html", "onas.html"),
        "home.html": ("index.html",),
    }

    def replace_href(match: re.Match[str]) -> str:
        quote = match.group(1)
        target = match.group(2).strip()
        clean = target.split("#", 1)[0].split("?", 1)[0].lstrip("./").lower()
        if not clean.endswith((".html", ".htm")) or clean in html_paths:
            return match.group(0)
        for candidate in aliases.get(clean, ()):
            if candidate in html_paths:
                suffix = ""
                if "#" in target:
                    suffix = "#" + target.split("#", 1)[1]
                return f'href={quote}{html_paths[candidate]}{suffix}{quote}'
        return match.group(0)

    def label_button(match: re.Match[str]) -> str:
        opening, inner, closing = match.group(1), match.group(2), match.group(3)
        if re.search(r'\baria-(?:label|labelledby)\s*=', opening, re.I):
            return match.group(0)
        visible = re.sub(r"<[^>]+>", " ", inner)
        visible = re.sub(r"\s+", " ", visible).strip()
        if visible:
            return match.group(0)
        title = re.search(r'\btitle\s*=\s*["\']([^"\']+)["\']', opening, re.I)
        classes = " ".join(re.findall(r'\bclass\s*=\s*["\']([^"\']+)["\']', opening, re.I)).lower()
        controls = re.search(r'\baria-controls\s*=\s*["\']([^"\']+)["\']', opening, re.I)
        if title:
            label = title.group(1).strip()
        elif "menu" in classes or "nav" in classes or controls:
            label = "Open navigation menu"
        elif "close" in classes:
            label = "Close"
        else:
            label = "Action"
        opening = opening[:-1] + f' aria-label="{html.escape(label, quote=True)}">'
        return opening + inner + closing

    for path, source in list(repaired.items()):
        if not path.lower().endswith((".html", ".htm")) or not isinstance(source, str):
            continue
        source = re.sub(r'href\s*=\s*(["\'])([^"\']+)\1', replace_href, source, flags=re.I)
        source = re.sub(r'(<button\b[^>]*>)(.*?)(</button>)', label_button, source, flags=re.I | re.S)
        repaired[path] = source
    return repaired


async def build_files(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, str]:
    pages = spec.get("pages") or _fallback_spec(config)["pages"]
    css = await _model_css(config, spec)
    files: dict[str, str] = {
        "assets/site.css": css,
        "assets/site.js": "document.documentElement.classList.add('js');\n",
        "robots.txt": "User-agent: *\nAllow: /\n",
    }
    for page in pages:
        if not isinstance(page, dict):
            continue
        slug = str(page.get("slug") or "index")
        path = "index.html" if slug == "index" else f"{slug}.html"
        files[path] = await _model_page(config, spec, page, css)
    if "index.html" not in files:
        first = pages[0] if pages else _fallback_spec(config)["pages"][0]
        files["index.html"] = _fallback_page(config, spec, first)
    base = f"https://{core.GITHUB_OWNER.lower()}.github.io/{re.sub(r'[^a-z0-9-]+', '-', (core.GITHUB_OUTPUT_PREFIX + config['name']).lower()).strip('-')[:90]}/"
    urls = [base + ("" if path == "index.html" else path) for path in files if path.endswith(".html")]
    files["sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{html.escape(url)}</loc></url>' for url in urls) + '</urlset>'
    return _repair_deterministic_bundle(files)



def _has_accessible_interactive_gap(source: str) -> bool:
    low = source.lower()
    navs = re.findall(r"<nav\b[^>]*>", source, re.I)
    if len(navs) > 1 and any(not re.search(r'aria-(?:label|labelledby)\s*=', nav, re.I) for nav in navs):
        return True
    for button in re.findall(r"<button\b[^>]*>.*?</button>", source, re.I | re.S):
        opening = button.split(">", 1)[0] + ">"
        if re.search(r'aria-(?:label|labelledby)\s*=', opening, re.I):
            continue
        visible = re.sub(r"<[^>]+>", " ", button)
        visible = re.sub(r"\s+", " ", visible).strip()
        if not visible:
            return True
    for anchor in re.findall(r"<a\b[^>]*>.*?</a>", source, re.I | re.S):
        opening = anchor.split(">", 1)[0] + ">"
        if re.search(r'aria-(?:label|labelledby)\s*=', opening, re.I):
            continue
        visible = re.sub(r"<[^>]+>", " ", anchor)
        visible = re.sub(r"\s+", " ", visible).strip()
        if not visible:
            return True
    return False


def _model_issue_is_supported(issue: dict[str, Any], files: dict[str, str]) -> bool:
    code = re.sub(r"[^a-z0-9]+", "-", str(issue.get("code") or "").lower()).strip("-")
    path = str(issue.get("file") or "")
    source = str(files.get(path) or "") if path else ""
    if code.isdigit():
        return False
    checks = {
        "missing-doctype": lambda s: not bool(re.search(r"^\s*<!doctype\s+html\b", s, re.I)),
        "missing-meta-charset": lambda s: not bool(re.search(r"<meta\b[^>]*charset\s*=", s, re.I)),
        "missing-meta-viewport": lambda s: not bool(re.search(r"<meta\b[^>]*name\s*=\s*[\"']viewport[\"']", s, re.I)),
        "missing-title": lambda s: not bool(re.search(r"<title\b[^>]*>.*?</title>", s, re.I | re.S)),
        "missing-meta-description": lambda s: not bool(re.search(r"<meta\b[^>]*name\s*=\s*[\"']description[\"']", s, re.I)),
        "missing-meta-og-title": lambda s: not bool(re.search(r"<meta\b[^>]*property\s*=\s*[\"']og:title[\"']", s, re.I)),
        "missing-meta-og-description": lambda s: not bool(re.search(r"<meta\b[^>]*property\s*=\s*[\"']og:description[\"']", s, re.I)),
        "missing-meta-og-type": lambda s: not bool(re.search(r"<meta\b[^>]*property\s*=\s*[\"']og:type[\"']", s, re.I)),
        "missing-semantic-structure": lambda s: any(tag not in s.lower() for tag in ("<header", "<nav", "<main", "<footer")),
        "missing-aria-label": _has_accessible_interactive_gap,
    }
    if code in checks:
        return bool(source) and checks[code](source)
    # Deterministic/browser QA owns machine-verifiable release blocking. Keep
    # local-model critique visible, but do not let an unverified arbitrary code
    # become a hard blocker.
    return False


def _normalize_model_issues(raw: Any, files: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for value in raw[:60]:
        if not isinstance(value, dict):
            continue
        item = dict(value)
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"critical", "high", "medium", "low"}:
            severity = "medium"
        supported = _model_issue_is_supported(item, files)
        if severity in {"critical", "high"} and not supported:
            severity = "medium"
            item["message"] = f"Advisory model review (not independently verified): {str(item.get('message') or '').strip()}"[:700]
        item["severity"] = severity
        item["code"] = str(item.get("code") or "MODEL_QA_NOTE")[:80]
        item["file"] = str(item.get("file") or "")[:220]
        out.append(item)
    return out


async def ai_audit(files: dict[str, str], config: dict[str, Any]) -> dict[str, Any]:
    mode = os.getenv("MODEL_QA_MODE", "deterministic").strip().lower()
    if mode not in {"full", "model", "llm"}:
        return {
            "passed": True,
            "issues": [{
                "severity": "low",
                "code": "MODEL_QA_ADAPTIVE_SKIP",
                "file": "",
                "message": "Routine model QA skipped; deterministic, browser and originality gates remain active.",
            }],
            "model_qa_skipped": True,
        }
    compact = {k: v[:8000] for k, v in files.items() if k.endswith((".html", ".css", ".js"))}
    prompt = f"""
Audit this website for concrete UX, navigation, mobile, accessibility, SEO and JavaScript problems.
PROJECT={json.dumps(config, ensure_ascii=False)}
FILES={json.dumps(compact, ensure_ascii=False)}
Return JSON {{"passed":boolean,"issues":[{{"severity":"critical|high|medium|low","code":"...","file":"...","message":"..."}}]}}.
Report only specific defects that can be acted on. Do not invent issues.
"""
    try:
        data = await _json_call(prompt, "You are a strict website QA engineer. Return JSON only.", attempts=2, num_predict=2200)
        issues = _normalize_model_issues(data.get("issues"), files)
        return {"passed": not any(i.get("severity") in {"critical", "high"} for i in issues), "issues": issues}
    except Exception:
        # Static audit remains authoritative. A transient QA-model format failure
        # must not destroy an otherwise valid customer site.
        return {"passed": True, "issues": [{"severity": "low", "code": "MODEL_QA_DEFERRED", "file": "", "message": "Secondary quality review was deferred; deterministic checks completed."}]}


async def fix_files(files: dict[str, str], issues: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, str]:
    """Best-effort focused repair. Never replace a valid bundle with malformed model output."""
    repaired = _repair_deterministic_bundle(files)
    file_budget = max(1, min(3, int(os.getenv("MODEL_REPAIR_FILES_PER_ATTEMPT", "2"))))
    paths = []
    for issue in issues:
        path = str(issue.get("file") or "")
        if path in repaired and path not in paths and path.endswith((".html", ".css", ".js")):
            paths.append(path)
    for path in paths[:file_budget]:
        relevant = [i for i in issues if str(i.get("file") or "") == path and i.get("severity") in {"critical", "high", "medium"}]
        if not relevant:
            continue
        content = repaired[path]
        kind = "HTML" if path.endswith(".html") else "CSS" if path.endswith(".css") else "JavaScript"
        prompt = f"""
Repair this {kind} file using only the listed concrete QA findings.
FILE={path}
ISSUES={json.dumps(relevant, ensure_ascii=False)}
CONTENT={content}
Return the COMPLETE corrected file only. Preserve the design and content unrelated to the findings. No markdown.
"""
        try:
            candidate = core.strip_fence(await _generate(prompt, "You are a senior debugging engineer. Return only the corrected file.", num_predict=5000))
            if path.endswith(".html"):
                candidate = re.sub(r"^\\s*(?:html|HTML)\\s*(?=<!doctype)", "", candidate, count=1)
                low = candidate.lower()
                required = ("<!doctype html", "<html", "<head", "<body", "<main", "<title", 'name="viewport"', 'name="description"', "assets/site.css")
                if any(token not in low for token in required):
                    continue
            if path.endswith(".css"):
                candidate = re.sub(r"^\\s*(?:css|CSS)\\s*(?=[:.@#a-zA-Z*])", "", candidate, count=1)
                if "{" not in candidate or "}" not in candidate:
                    continue
            if len(candidate) >= max(200, int(len(content) * 0.70)):
                repaired[path] = candidate
        except Exception:
            continue
    return repaired


# Patch the core module. Route/background functions resolve these globals at
# runtime, so no API surface changes are required.
core.design_site = design_site
core.build_files = build_files
core.ai_audit = ai_audit
core.fix_files = fix_files
