"""Bounded GitHub-hosted Project Visibility preview worker.

Creates a static website preview artifact from an operator-supplied JSON brief.
No local Agent Manager model/CPU, no Git push, no production deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from api import premium_generation

SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_BRIEF_BYTES = 12000
MAX_PAGES = 8


def _brief(path: Path) -> tuple[dict, dict]:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_BRIEF_BYTES:
        raise ValueError("Brief must contain 1..12000 UTF-8 bytes.")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON brief must be an object.")
    name = str(value.get("name") or "").strip()[:90]
    if not name:
        raise ValueError("A project name is required.")
    raw_pages = value.get("pages")
    if not isinstance(raw_pages, list) or not 1 <= len(raw_pages) <= MAX_PAGES:
        raise ValueError("Provide 1..8 website pages.")
    pages, seen = [], set()
    for item in raw_pages:
        if not isinstance(item, dict):
            raise ValueError("Each page must be an object.")
        slug = str(item.get("slug") or "").lower()
        if not SAFE_SLUG.fullmatch(slug) or slug in seen:
            raise ValueError("Duplicate or unsafe page slug.")
        seen.add(slug)
        title = str(item.get("title") or "").strip()[:110]
        if not title:
            raise ValueError("Every page needs a title.")
        pages.append({
            "slug": slug,
            "title": title,
            "purpose": str(item.get("purpose") or title)[:380],
            "sections": (item.get("sections") if isinstance(item.get("sections"), list) else [])[:12],
        })
    if "index" not in seen:
        raise ValueError("At least one page slug must be 'index'.")
    config = {
        "name": name, "organization": str(value.get("organization") or name)[:90],
        "language": "sl" if str(value.get("language") or "").lower() in ("sl", "slovenian") else "en",
        "programme": str(value.get("programme") or "")[:180],
        "goal": str(value.get("goal") or "")[:600],
        "hero_title": str(value.get("hero_title") or name)[:160],
        "hero_subtitle": str(value.get("hero_subtitle") or "")[:350],
        "cta_text": str(value.get("cta_text") or "")[:65],
        "brand": {
            "primary_color": str((value.get("brand") or {}).get("primary_color") or "#17324d")[:12],
            "secondary_color": str((value.get("brand") or {}).get("secondary_color") or "#7eb6a1")[:12],
            "background_color": str((value.get("brand") or {}).get("background_color") or "#f2f4f1")[:12],
            "text_color": str((value.get("brand") or {}).get("text_color") or "#17212b")[:12],
        },
    }
    return config, {"site_name": name, "pages": pages, "language": config["language"]}


def build_preview(brief_file: Path, output: Path) -> dict:
    config, spec = _brief(brief_file)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty.")
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    files = {}
    for idx, page in enumerate(spec["pages"]):
        filename = f"{page['slug']}.html"
        html = premium_generation._render_page(config, spec, page, idx)
        if "<!doctype html>" not in html.lower() or 'name="viewport"' not in html:
            raise RuntimeError(f"Quality check failed for {filename}.")
        files[filename] = html
    files["assets/site.css"] = premium_generation._css(config)
    files["assets/site.js"] = (
        'const b=document.querySelector(".menu"),n=document.querySelector(".nav-links");'
        'if(b&&n)b.addEventListener("click",()=>{const x=b.getAttribute("aria-expanded")==="true";'
        'b.setAttribute("aria-expanded",String(!x));n.classList.toggle("open",!x)});'
    )
    for rel, content in files.items():
        destination = output / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    hashes = {
        rel: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for rel, content in sorted(files.items())
    }
    manifest = {
        "worker": "pv-remote-preview-v8",
        "mode": "preview_only_no_deploy",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "pages": list(sorted(x for x in files if x.endswith(".html"))),
        "files_sha256": hashes,
        "approval_required_for_deploy": True,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_preview(args.brief_file, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
