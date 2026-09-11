"""Media rendering layer for the premium site generator.

Wraps the existing premium renderer: the first auto/hero image becomes an
art-directed hero visual, while remaining uploads form a responsive gallery.
No model is asked to recreate or hallucinate customer images.
"""

from __future__ import annotations

import html
import re

import api.main as core

_base_build_files = core.build_files


def _e(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value or ""), quote=quote)


def _media_css() -> str:
    return r'''
.user-hero-image{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;z-index:2;filter:saturate(.94) contrast(1.02)}
.hero-art:has(.user-hero-image) .visual{opacity:0}.hero-art:has(.user-hero-image)::after{content:"";position:absolute;inset:0;z-index:3;border-radius:inherit;background:linear-gradient(180deg,transparent 48%,rgba(3,19,15,.34));pointer-events:none}
.media-section{padding:clamp(4rem,8vw,8rem) 0}.media-head{display:grid;grid-template-columns:.7fr 1.3fr;gap:2rem;align-items:end;margin-bottom:2rem}.media-head h2{margin:0;font-size:clamp(2.2rem,5vw,5rem);line-height:.95;letter-spacing:-.055em}.media-head p{max-width:38rem;margin:0;opacity:.7}.media-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:1rem}.media-item{grid-column:span 4;min-height:24rem;margin:0;overflow:hidden;border-radius:22px;background:#dfe7e2;position:relative}.media-item:nth-child(4n+1){grid-column:span 7}.media-item:nth-child(4n+2){grid-column:span 5}.media-item img{width:100%;height:100%;min-height:24rem;object-fit:cover;display:block;transition:transform .6s cubic-bezier(.2,.7,.2,1)}.media-item:hover img{transform:scale(1.025)}.media-item figcaption{position:absolute;left:1rem;right:1rem;bottom:1rem;padding:.55rem .7rem;border-radius:999px;background:rgba(6,24,19,.72);backdrop-filter:blur(10px);color:#fff;font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:820px){.media-head{grid-template-columns:1fr}.media-item,.media-item:nth-child(n){grid-column:1/-1;min-height:18rem}.media-item img{min-height:18rem}.user-hero-image{min-height:100%}}
'''.strip()


def _hero_image(images: list[dict]) -> dict | None:
    explicit = next((x for x in images if x.get("placement") == "hero"), None)
    if explicit:
        return explicit
    return next((x for x in images if x.get("placement") == "auto"), None)


def _gallery_images(images: list[dict], hero: dict | None) -> list[dict]:
    result = []
    for image in images:
        if hero and image.get("repo_path") == hero.get("repo_path") and len(images) > 1:
            continue
        if image.get("placement") in {"gallery", "content", "auto", "hero"}:
            result.append(image)
    return result


def _gallery_section(images: list[dict]) -> str:
    if not images:
        return ""
    items = []
    for image in images:
        src = _e(image.get("repo_path"), quote=True)
        alt = _e(image.get("alt_text") or image.get("original_name") or "Project image", quote=True)
        caption = _e(image.get("alt_text") or image.get("original_name") or "")
        figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
        items.append(f'<figure class="media-item reveal"><img src="{src}" alt="{alt}" loading="lazy" decoding="async">{figcaption}</figure>')
    return f'''<section class="media-section" id="gallery"><div class="shell">
      <div class="media-head reveal"><div><span class="label">Gallery</span><h2>Project in focus.</h2></div><p>Original images supplied for this project are integrated directly into the published website.</p></div>
      <div class="media-grid">{''.join(items)}</div>
    </div></section>'''


def _decorate_html(source: str, images: list[dict], *, gallery: bool) -> str:
    hero = _hero_image(images)
    if hero:
        src = _e(hero.get("repo_path"), quote=True)
        alt = _e(hero.get("alt_text") or hero.get("original_name") or "Project image", quote=True)
        image_html = f'<img class="user-hero-image" src="{src}" alt="{alt}" fetchpriority="high" decoding="async">'
        source, _ = re.subn(
            r'(<div class="hero-art reveal">)',
            r'\1' + image_html,
            source,
            count=1,
        )
    if gallery:
        section = _gallery_section(_gallery_images(images, hero))
        if section:
            source = source.replace("</main>", section + "</main>", 1)
    return source


async def build_files_with_media(config: dict, spec: dict) -> dict:
    files = await _base_build_files(config, spec)
    images = [x for x in (config.get("uploaded_images") or []) if isinstance(x, dict) and x.get("repo_path")]
    if not images:
        return files

    css = str(files.get("assets/site.css") or "")
    files["assets/site.css"] = css + "\n\n" + _media_css() + "\n"

    gallery_paths = {
        "index.html",
        *[f"{p.get('slug')}.html" for p in (spec.get("pages") or []) if "gallery" in str(p.get("slug") or "").lower() or "galer" in str(p.get("slug") or "").lower()],
    }
    for path, content in list(files.items()):
        if not path.endswith(".html"):
            continue
        files[path] = _decorate_html(str(content), images, gallery=path in gallery_paths)
    return files


core.build_files = build_files_with_media
