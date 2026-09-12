"""Media rendering layer for the premium site generator.

Uploaded customer images remain local binary assets. The renderer places them
only where the user requested: homepage hero/gallery/content, or a specific page
and role such as page:programme:hero. No model recreates or hallucinates them.
"""

from __future__ import annotations

import html
import re
from pathlib import PurePosixPath

import api.main as core

_base_build_files = core.build_files


def _e(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value or ""), quote=quote)


def _media_css() -> str:
    return r'''
.user-hero-image{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;z-index:2;filter:saturate(.96) contrast(1.03)}
.hero-art:has(.user-hero-image) .visual{opacity:0}.hero-art:has(.user-hero-image)::after{content:"";position:absolute;inset:0;z-index:3;border-radius:inherit;background:linear-gradient(180deg,transparent 45%,rgba(3,19,15,.38));pointer-events:none}
.media-section{padding:clamp(4rem,8vw,8rem) 0}.media-head{display:grid;grid-template-columns:.7fr 1.3fr;gap:2rem;align-items:end;margin-bottom:2rem}.media-head h2{margin:0;font-size:clamp(2.2rem,5vw,5rem);line-height:.95;letter-spacing:-.055em}.media-head p{max-width:38rem;margin:0;opacity:.7}.media-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:1rem}.media-item{grid-column:span 4;min-height:24rem;margin:0;overflow:hidden;border-radius:22px;background:#dfe7e2;position:relative}.media-item:nth-child(4n+1){grid-column:span 7}.media-item:nth-child(4n+2){grid-column:span 5}.media-item img{width:100%;height:100%;min-height:24rem;object-fit:cover;display:block;transition:transform .6s cubic-bezier(.2,.7,.2,1)}.media-item:hover img{transform:scale(1.025)}.media-item figcaption{position:absolute;left:1rem;right:1rem;bottom:1rem;padding:.55rem .7rem;border-radius:999px;background:rgba(6,24,19,.72);backdrop-filter:blur(10px);color:#fff;font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.content-media{padding:0 0 clamp(4rem,7vw,7rem)}.content-media .media-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.content-media .media-item,.content-media .media-item:nth-child(n){grid-column:auto;min-height:20rem}.content-media .media-item img{min-height:20rem}
@media(max-width:820px){.media-head{grid-template-columns:1fr}.media-item,.media-item:nth-child(n),.content-media .media-item,.content-media .media-item:nth-child(n){grid-column:1/-1;min-height:18rem}.media-item img,.content-media .media-item img{min-height:18rem}.content-media .media-grid{grid-template-columns:1fr}.user-hero-image{min-height:100%}}
'''.strip()


def _placement(image: dict) -> tuple[str | None, str]:
    raw = str(image.get("placement") or "auto").strip().lower()
    if raw.startswith("page:"):
        parts = raw.split(":", 2)
        if len(parts) == 3 and parts[1] and parts[2] in {"hero", "gallery", "content"}:
            return parts[1], parts[2]
    if raw in {"hero", "gallery", "content", "auto"}:
        return None, raw
    return None, "auto"


def _page_slug(path: str) -> str:
    name = PurePosixPath(path).name
    return "index" if name == "index.html" else PurePosixPath(name).stem


def _matches(image: dict, page_slug: str, role: str) -> bool:
    target_page, target_role = _placement(image)
    if target_page is not None:
        return target_page == page_slug and target_role == role
    if page_slug != "index":
        return False
    if target_role == role:
        return True
    return target_role == "auto" and role == "gallery"


def _hero_image(images: list[dict], page_slug: str) -> dict | None:
    explicit = next((x for x in images if _matches(x, page_slug, "hero")), None)
    if explicit:
        return explicit
    # Only the homepage gets an automatic hero fallback.
    if page_slug == "index":
        return next((x for x in images if _placement(x) == (None, "auto")), None)
    return None


def _section_images(images: list[dict], page_slug: str, role: str, hero: dict | None) -> list[dict]:
    result: list[dict] = []
    for image in images:
        if hero and image.get("repo_path") == hero.get("repo_path"):
            continue
        target_page, target_role = _placement(image)
        if target_page is not None:
            if target_page == page_slug and target_role == role:
                result.append(image)
            continue
        if page_slug != "index":
            continue
        if target_role == role or (target_role == "auto" and role == "gallery"):
            result.append(image)
    return result


def _media_section(images: list[dict], *, compact: bool, heading: str, label: str) -> str:
    if not images:
        return ""
    items = []
    for image in images:
        src = _e(image.get("repo_path"), quote=True)
        alt = _e(image.get("alt_text") or image.get("original_name") or "Project image", quote=True)
        caption = _e(image.get("alt_text") or image.get("original_name") or "")
        figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
        items.append(f'<figure class="media-item reveal"><img src="{src}" alt="{alt}" loading="lazy" decoding="async">{figcaption}</figure>')
    cls = "media-section content-media" if compact else "media-section"
    return f'''<section class="{cls}"><div class="shell">
      <div class="media-head reveal"><div><span class="label">{_e(label)}</span><h2>{_e(heading)}</h2></div><p>Original project imagery is integrated directly into this page and remains part of the delivered source.</p></div>
      <div class="media-grid">{''.join(items)}</div>
    </div></section>'''


def _decorate_html(source: str, images: list[dict], page_slug: str) -> str:
    hero = _hero_image(images, page_slug)
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

    content_images = _section_images(images, page_slug, "content", hero)
    gallery_images = _section_images(images, page_slug, "gallery", hero)

    content_section = _media_section(content_images, compact=True, heading="Inside the work.", label="In focus")
    gallery_section = _media_section(gallery_images, compact=False, heading="Project in focus.", label="Gallery")

    insertion = content_section + gallery_section
    if insertion:
        source = source.replace("</main>", insertion + "</main>", 1)
    return source


async def build_files_with_media(config: dict, spec: dict) -> dict:
    files = await _base_build_files(config, spec)
    images = [x for x in (config.get("uploaded_images") or []) if isinstance(x, dict) and x.get("repo_path")]
    if not images:
        return files

    css = str(files.get("assets/site.css") or "")
    files["assets/site.css"] = css + "\n\n" + _media_css() + "\n"

    for path, content in list(files.items()):
        if not path.endswith(".html"):
            continue
        files[path] = _decorate_html(str(content), images, _page_slug(path))
    return files


core.build_files = build_files_with_media
