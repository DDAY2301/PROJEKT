"""Premium deterministic renderer for generated websites.

The local model remains responsible for information architecture and copy, but
visual quality is no longer delegated to raw model HTML/CSS. This module adds a
stable design floor inspired by strong contemporary editorial/project sites:
large art-directed heroes, disciplined grids, rich section rhythm, metrics,
cross-page discovery, accessible navigation, responsive behaviour and subtle
motion. It intentionally does not copy any third-party site's code or assets.
"""

from __future__ import annotations

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


def _sentences(value: Any, limit: int = 3) -> list[str]:
    raw = _text(value)
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+", raw)
    return [p.strip() for p in parts if p.strip()][:limit]


def _configured_brand(config: dict[str, Any]) -> dict[str, str]:
    brand = config.get("brand") or {}
    return {
        "primary": _hex(brand.get("primary_color"), "#0B1F33"),
        "accent": _hex(brand.get("secondary_color"), "#C7FF4A"),
        "background": _hex(brand.get("background_color"), "#F7F4EC"),
        "text": _hex(brand.get("text_color"), "#10212B"),
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


def _render_visual(label: str, index: int = 0) -> str:
    safe = _e(label[:32] or "Explore")
    return f'''<div class="visual visual-{index % 4}" aria-hidden="true">
      <div class="visual-grid"></div><div class="visual-orb visual-orb-a"></div><div class="visual-orb visual-orb-b"></div>
      <span class="visual-kicker">0{(index % 9) + 1}</span><strong>{safe}</strong><span class="visual-arrow">↗</span>
    </div>'''


def _render_crosslinks(spec: dict[str, Any], current_slug: str) -> str:
    cards = []
    for idx, p in enumerate(spec.get("pages") or []):
        slug = str(p.get("slug") or "index")
        if slug == current_slug:
            continue
        title = _e(p.get("title") or "Explore")
        purpose = _e(_text(p.get("purpose"), "Discover this part of the project."))
        cards.append(
            f'''<a class="story-card reveal" href="{_e(_href(slug), quote=True)}">
              {_render_visual(str(p.get("title") or "Explore"), idx)}
              <div class="story-card-copy"><span>Explore</span><h3>{title}</h3><p>{purpose}</p><b>Open page ↗</b></div>
            </a>'''
        )
        if len(cards) == 3:
            break
    if not cards:
        return ""
    return f'''<section class="section section-ink"><div class="shell">
      <div class="section-head reveal"><span class="label">Explore</span><h2>More of the story.</h2></div>
      <div class="story-grid">{''.join(cards)}</div>
    </div></section>'''


def _render_content_sections(page: dict[str, Any]) -> str:
    out: list[str] = []
    sections = [s for s in (page.get("sections") or []) if isinstance(s, dict)]
    filtered = [s for s in sections if str(s.get("type") or "").lower() not in {"hero", "cta"}]
    for idx, section in enumerate(filtered[:4]):
        heading = _e(_text(section.get("heading"), page.get("title") or "Overview"))
        body = _text(section.get("body"), page.get("purpose") or "")
        paras = _sentences(body, 4) or [body]
        body_html = "".join(f"<p>{_e(p)}</p>" for p in paras if p)
        variant = "section-split" if idx % 2 == 0 else "section-split section-split-reverse"
        out.append(f'''<section class="section"><div class="shell {variant}">
          <div class="section-head reveal"><span class="label">{_e(section.get('type') or 'Overview')}</span><h2>{heading}</h2></div>
          <div class="prose reveal">{body_html}</div>
        </div></section>''')
    return "".join(out)


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


def _render_contact(config: dict[str, Any]) -> str:
    email = _text(config.get("contact_email"))
    if not email:
        return ""
    return f'''<section class="section contact-panel"><div class="shell contact-grid">
      <div class="section-head reveal"><span class="label">Contact</span><h2>Start a conversation.</h2><p>Tell us what you are working on and what kind of collaboration you have in mind.</p></div>
      <div class="contact-box reveal"><span>Email</span><a href="mailto:{_e(email, quote=True)}">{_e(email)}</a><p>We will use your message only to respond to your enquiry.</p></div>
    </div></section>'''


def _render_cta(config: dict[str, Any]) -> str:
    label = _e(_text(config.get("cta_text"), "Contact us"))
    return f'''<section class="section final-cta"><div class="shell reveal">
      <span class="label">Next step</span><h2>Turn intention into something people can join.</h2>
      <a class="button button-accent" href="contact.html">{label}<span>↗</span></a>
    </div></section>'''


def _render_page(config: dict[str, Any], spec: dict[str, Any], page: dict[str, Any], index: int) -> str:
    slug = str(page.get("slug") or "index")
    is_home = slug == "index"
    site_name = _text(spec.get("site_name"), config.get("organization") or config.get("name") or "Website")
    page_title = _text(page.get("title"), "Home")
    meta = _text(page.get("meta_description"), page.get("purpose") or config.get("goal") or "")[:160]
    nav = _navigation(spec, slug)
    hero_title = _text(config.get("hero_title"), page_title) if is_home else page_title
    hero_body = _text(config.get("hero_subtitle"), page.get("purpose") or config.get("goal") or "") if is_home else _text(page.get("purpose"), config.get("goal") or "")
    programme = _text(config.get("programme"), "Project / digital experience")
    email = _text(config.get("contact_email"))

    body = [f'''<section class="hero {'hero-home' if is_home else 'hero-inner'}"><div class="shell hero-grid">
      <div class="hero-copy reveal"><span class="label label-light">{_e(programme)}</span><h1>{_e(hero_title)}</h1><p>{_e(hero_body)}</p>
      <div class="hero-actions"><a class="button button-accent" href="{'programme.html' if is_home and any(str(p.get('slug')) == 'programme' for p in spec.get('pages') or []) else 'contact.html'}">{_e(config.get('cta_text') or 'Explore')}<span>↗</span></a><a class="text-link" href="#content">Discover more ↓</a></div>
      </div><div class="hero-art reveal">{_render_visual(page_title, index)}<div class="hero-note"><span>Project</span><strong>{_e(site_name)}</strong></div></div>
    </div></section>''']

    if is_home:
        body.append(f'''<section class="section intro" id="content"><div class="shell intro-grid">
          <div class="section-head reveal"><span class="label">Why it matters</span><h2>{_e(_text(config.get('goal'), 'A clearer way to turn ideas into action.'))}</h2></div>
          <div class="prose reveal"><p>{_e(_text(page.get('purpose'), hero_body))}</p><p>{_e(_text(config.get('tone'), 'Clear, human and practical.'))}</p></div>
        </div></section>''')
        body.append(_render_journey(config))
        body.append(_render_metrics(config))
    else:
        body.append('<div id="content"></div>')

    body.append(_render_content_sections(page))
    body.append(_render_crosslinks(spec, slug))
    if "contact" in slug.lower() or page_title.lower() == "contact":
        body.append(_render_contact(config))
    body.append(_render_cta(config))

    contact_link = f'<a href="mailto:{_e(email, quote=True)}">{_e(email)}</a>' if email else ""
    return f'''<!doctype html>
<html lang="{_e(config.get('language') or 'en', quote=True)}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(page_title)} | {_e(site_name)}</title><meta name="description" content="{_e(meta, quote=True)}">
<meta property="og:title" content="{_e(page_title, quote=True)} | {_e(site_name, quote=True)}"><meta property="og:description" content="{_e(meta, quote=True)}"><meta property="og:type" content="website">
<meta name="theme-color" content="{_configured_brand(config)['primary']}"><link rel="stylesheet" href="assets/site.css">
</head>
<body class="page page-{_e(slug, quote=True)}"><a class="skip" href="#content">Skip to content</a>
<header class="site-header"><div class="shell nav"><a class="brand" href="index.html"><span class="brand-mark">N</span><span>{_e(site_name)}</span></a><button class="menu" type="button" aria-expanded="false" aria-controls="navLinks"><span></span><span></span></button><nav id="navLinks" class="nav-links" aria-label="Primary">{nav}</nav></div></header>
<main>{''.join(body)}</main>
<footer class="site-footer"><div class="shell footer-grid"><div><a class="brand brand-footer" href="index.html"><span class="brand-mark">N</span><span>{_e(site_name)}</span></a><p>{_e(_text(config.get('goal'), 'A project built for meaningful participation.'))}</p></div><div><span class="footer-label">Navigate</span><nav class="footer-nav">{nav}</nav></div><div><span class="footer-label">Contact</span>{contact_link or '<span>Use the contact page</span>'}</div></div><div class="shell footer-bottom"><span>© { _e(site_name) }</span><span>Responsive · accessible · lightweight</span></div></footer>
<script src="assets/site.js" defer></script></body></html>'''


def _css(config: dict[str, Any]) -> str:
    b = _configured_brand(config)
    return f''':root{{--primary:{b['primary']};--accent:{b['accent']};--bg:{b['background']};--ink:{b['text']};--paper:#fff;--muted:#667770;--dark:#071d18;--dark2:#0d2b24;--line:rgba(16,33,43,.14);--shell:1240px;--radius:28px}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.6 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}}a{{color:inherit}}img{{max-width:100%}}.shell{{width:min(var(--shell),calc(100% - 48px));margin:auto}}.skip{{position:fixed;left:16px;top:-80px;z-index:1000;background:var(--accent);color:#071d18;padding:12px 16px;border-radius:999px;font-weight:800}}.skip:focus{{top:16px}}a:focus-visible,button:focus-visible{{outline:3px solid var(--accent);outline-offset:4px}}
.site-header{{position:fixed;inset:0 0 auto;z-index:100;border-bottom:1px solid rgba(255,255,255,.12);background:rgba(7,29,24,.82);backdrop-filter:blur(18px)}}.nav{{min-height:82px;display:flex;align-items:center;gap:28px}}.brand{{display:flex;align-items:center;gap:10px;color:#fff;font-weight:850;text-decoration:none;letter-spacing:-.025em}}.brand-mark{{width:32px;height:32px;display:grid;place-items:center;border-radius:10px;background:var(--accent);color:#071d18;font-size:13px;font-weight:950}}.nav-links{{margin-left:auto;display:flex;align-items:center;gap:26px}}.nav-links a{{position:relative;color:#dce9e5;text-decoration:none;font-size:14px;font-weight:650}}.nav-links a::after{{content:"";position:absolute;left:0;right:100%;bottom:-7px;height:2px;background:var(--accent);transition:.25s}}.nav-links a:hover::after,.nav-links a[aria-current="page"]::after{{right:0}}.menu{{display:none;margin-left:auto;width:44px;height:44px;border:1px solid rgba(255,255,255,.18);border-radius:14px;background:transparent}}.menu span{{display:block;width:18px;height:2px;margin:5px auto;background:#fff}}
.hero{{position:relative;overflow:hidden;background:linear-gradient(135deg,var(--dark) 0%,var(--primary) 68%,var(--dark2) 100%);color:#fff}}.hero::after{{content:"";position:absolute;right:-12vw;top:-18vw;width:45vw;height:45vw;border:1px solid rgba(199,255,74,.18);border-radius:50%;box-shadow:0 0 0 80px rgba(199,255,74,.035),0 0 0 160px rgba(199,255,74,.02)}}.hero-grid{{position:relative;z-index:2;min-height:760px;padding:150px 0 84px;display:grid;grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr);align-items:center;gap:72px}}.hero-inner .hero-grid{{min-height:620px}}.hero-copy h1{{max-width:940px;margin:18px 0 26px;font-size:clamp(58px,7.4vw,118px);line-height:.88;letter-spacing:-.075em;font-weight:900;text-wrap:balance}}.hero-inner .hero-copy h1{{font-size:clamp(54px,6vw,92px)}}.hero-copy p{{max-width:720px;margin:0;color:#c7d7d2;font-size:clamp(18px,1.7vw,24px);line-height:1.5}}.label{{display:inline-flex;align-items:center;gap:9px;font-size:12px;font-weight:850;letter-spacing:.12em;text-transform:uppercase;color:var(--primary)}}.label::before{{content:"";width:22px;height:2px;background:currentColor}}.label-light{{color:var(--accent)}}.hero-actions{{display:flex;align-items:center;gap:24px;margin-top:38px;flex-wrap:wrap}}.button{{display:inline-flex;align-items:center;justify-content:center;gap:14px;min-height:54px;padding:0 22px;border-radius:999px;text-decoration:none;font-weight:800;transition:transform .25s,box-shadow .25s}}.button:hover{{transform:translateY(-3px)}}.button-accent{{background:var(--accent);color:#071d18;box-shadow:0 14px 40px rgba(199,255,74,.12)}}.button span{{font-size:18px}}.text-link{{color:#e6f0ed;text-underline-offset:5px;font-weight:650}}
.hero-art{{position:relative;min-height:440px}}.visual{{position:relative;min-height:420px;height:100%;overflow:hidden;border-radius:var(--radius);background:linear-gradient(145deg,#f8f5ec 0%,#dce7df 100%);color:#071d18;box-shadow:0 42px 90px rgba(0,0,0,.28)}}.visual-grid{{position:absolute;inset:0;background-image:linear-gradient(rgba(7,29,24,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(7,29,24,.08) 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(to bottom,#000,transparent)}}.visual-orb{{position:absolute;border-radius:50%;filter:blur(1px)}}.visual-orb-a{{width:240px;height:240px;right:-35px;top:42px;background:var(--accent);box-shadow:0 0 0 26px rgba(199,255,74,.22)}}.visual-orb-b{{width:150px;height:150px;left:54px;bottom:42px;background:var(--primary);opacity:.88}}.visual strong{{position:absolute;left:34px;bottom:34px;z-index:3;max-width:70%;font-size:clamp(30px,3vw,52px);line-height:.95;letter-spacing:-.055em}}.visual-kicker{{position:absolute;left:34px;top:28px;z-index:3;font-size:13px;font-weight:900}}.visual-arrow{{position:absolute;right:30px;bottom:26px;z-index:3;font-size:32px}}.hero-note{{position:absolute;right:-18px;bottom:-18px;z-index:4;width:190px;padding:18px 20px;border-radius:20px;background:#fff;color:var(--ink);box-shadow:0 22px 50px rgba(0,0,0,.22)}}.hero-note span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em}}.hero-note strong{{display:block;margin-top:4px;line-height:1.15}}
.section{{padding:112px 0}}.section:nth-of-type(even):not(.hero):not(.section-ink):not(.metric-band):not(.final-cta){{background:rgba(255,255,255,.42)}}.section-head h2{{max-width:820px;margin:16px 0 0;font-size:clamp(42px,5.4vw,78px);line-height:.98;letter-spacing:-.06em;text-wrap:balance}}.section-head>p{{max-width:620px;color:var(--muted);font-size:18px}}.intro-grid,.section-split{{display:grid;grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:clamp(60px,9vw,140px);align-items:start}}.section-split-reverse{{grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr)}}.section-split-reverse .section-head{{order:2}}.prose{{max-width:720px;padding-top:10px}}.prose p{{margin:0 0 22px;font-size:clamp(18px,1.6vw,22px);line-height:1.65;color:#42564f}}.prose p:first-child{{font-size:clamp(24px,2.4vw,34px);line-height:1.4;color:var(--ink);letter-spacing:-.025em}}
.journey{{background:#fff}}.steps{{display:grid;grid-template-columns:repeat(4,1fr);margin-top:60px;border-top:1px solid var(--line)}}.step{{position:relative;padding:30px 26px 18px 0;min-height:180px;border-right:1px solid var(--line)}}.step:last-child{{border-right:0}}.step>span{{font-size:12px;color:var(--muted);font-weight:800}}.step h3{{margin:36px 0 0;font-size:clamp(26px,2.5vw,40px);letter-spacing:-.04em}}.step-line{{position:absolute;left:0;top:-2px;width:48%;height:3px;background:var(--accent)}}
.metric-band{{background:var(--accent);color:#071d18}}.metric-band .label{{color:#071d18}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);margin-top:54px;border-top:1px solid rgba(7,29,24,.24)}}.metric{{padding:28px 20px 10px 0;border-right:1px solid rgba(7,29,24,.24)}}.metric:last-child{{border-right:0}}.metric strong{{display:block;font-size:clamp(46px,6vw,86px);line-height:1;letter-spacing:-.065em}}.metric span{{display:block;margin-top:10px;font-weight:700}}
.section-ink{{background:var(--dark);color:#fff}}.section-ink .label{{color:var(--accent)}}.story-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:54px}}.story-card{{display:flex;min-height:560px;flex-direction:column;border:1px solid rgba(255,255,255,.12);border-radius:var(--radius);overflow:hidden;background:#0b2620;color:#fff;text-decoration:none;transition:transform .3s,border-color .3s}}.story-card:hover{{transform:translateY(-6px);border-color:rgba(199,255,74,.6)}}.story-card .visual{{min-height:270px;height:270px;border-radius:0;box-shadow:none}}.story-card-copy{{padding:26px}}.story-card-copy>span{{color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.12em;font-weight:850}}.story-card h3{{margin:9px 0 12px;font-size:30px;line-height:1;letter-spacing:-.04em}}.story-card p{{margin:0;color:#aebfba}}.story-card b{{display:block;margin-top:auto;padding-top:22px;font-size:13px;color:var(--accent)}}
.contact-panel{{background:#fff}}.contact-grid{{display:grid;grid-template-columns:1fr .8fr;gap:80px;align-items:center}}.contact-box{{padding:38px;border-radius:var(--radius);background:var(--bg);border:1px solid var(--line)}}.contact-box>span{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.12em}}.contact-box>a{{display:block;margin-top:12px;font-size:clamp(26px,3vw,44px);line-height:1.1;letter-spacing:-.045em;font-weight:850;word-break:break-word}}.contact-box p{{color:var(--muted)}}.final-cta{{background:linear-gradient(135deg,var(--primary),var(--dark));color:#fff}}.final-cta .label{{color:var(--accent)}}.final-cta h2{{max-width:900px;margin:18px 0 34px;font-size:clamp(50px,6vw,92px);line-height:.92;letter-spacing:-.065em}}
.site-footer{{padding:76px 0 28px;background:#061914;color:#d7e5e1}}.footer-grid{{display:grid;grid-template-columns:1.3fr .7fr .7fr;gap:60px;padding-bottom:58px}}.brand-footer{{margin-bottom:20px}}.footer-grid p{{max-width:430px;color:#829993}}.footer-label{{display:block;margin-bottom:16px;color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.14em;font-weight:850}}.footer-nav{{display:grid;gap:8px}}.footer-nav a,.footer-grid a{{color:#d7e5e1;text-decoration:none}}.footer-bottom{{padding-top:22px;border-top:1px solid rgba(255,255,255,.12);display:flex;justify-content:space-between;gap:20px;color:#759089;font-size:12px}}
.js .reveal{{opacity:0;transform:translateY(18px);transition:opacity .65s ease,transform .65s ease}}.js .reveal.is-visible{{opacity:1;transform:none}}
@media(max-width:980px){{.hero-grid{{grid-template-columns:1fr;min-height:auto;padding-top:142px}}.hero-art{{min-height:360px}}.intro-grid,.section-split,.section-split-reverse,.contact-grid{{grid-template-columns:1fr;gap:42px}}.section-split-reverse .section-head{{order:0}}.steps,.metrics{{grid-template-columns:repeat(2,1fr)}}.story-grid{{grid-template-columns:1fr 1fr}}.footer-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:760px){{.shell{{width:min(100% - 28px,var(--shell))}}.nav{{min-height:70px}}.menu{{display:block}}.nav-links{{display:none;position:absolute;left:14px;right:14px;top:76px;padding:18px;border-radius:20px;background:#08221c;box-shadow:0 25px 60px rgba(0,0,0,.3);flex-direction:column;align-items:stretch;gap:0}}.nav-links.open{{display:flex}}.nav-links a{{padding:12px}}.hero-grid{{padding:120px 0 62px;gap:42px}}.hero-copy h1{{font-size:clamp(48px,15vw,76px)}}.hero-art,.visual{{min-height:330px}}.hero-note{{right:12px;bottom:-12px}}.section{{padding:78px 0}}.section-head h2{{font-size:clamp(38px,11vw,56px)}}.steps,.metrics,.story-grid,.footer-grid{{grid-template-columns:1fr}}.step,.metric{{border-right:0;border-bottom:1px solid var(--line)}}.story-card{{min-height:0}}.footer-bottom{{flex-direction:column}}}}
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
    return files


# Premium renderer loads after robust_generation and replaces only planning/build.
# Existing QA/self-fix functions remain active.
core.design_site = design_site
core.build_files = build_files
