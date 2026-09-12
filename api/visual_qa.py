"""Rendered visual QA for generated websites.

The text/model audits catch structural defects, but they cannot prove that a page
actually renders well. This module writes a candidate bundle to a temporary
local web root, opens every HTML page in headless Chromium at desktop, tablet
and mobile sizes, saves screenshots, and runs deterministic render checks for
layout overflow, typography, hero visibility, navigation, CTA visibility,
broken images, contrast and suspicious empty space.

Screenshots stay local under api/data/visual-qa and are not published to a
customer repository. Browser-based QA is intentionally deterministic: the
results are converted to normal QA issues so the existing bounded repair loop
can fix them and render again before publication.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

import api.main as core

QA_ROOT = Path(os.getenv("VISUAL_QA_ROOT", "api/data/visual-qa"))
QA_ROOT.mkdir(parents=True, exist_ok=True)
MAX_VISUAL_PAGES = int(os.getenv("VISUAL_QA_MAX_PAGES", "12"))

VIEWPORTS: dict[str, tuple[int, int]] = {
    "desktop": (1440, 1000),
    "tablet": (834, 1112),
    "mobile": (390, 844),
}


def _issue(severity: str, code: str, file: str, message: str, viewport: str = "") -> dict[str, str]:
    out = {"severity": severity, "code": code, "file": file, "message": message}
    if viewport:
        out["viewport"] = viewport
    return out


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        return


def _write_candidate(root: Path, files: dict[str, Any], uploaded_images: list[dict[str, Any]]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(str(content), encoding="utf-8")

    # During first-build QA the binary images are not yet attached to the model
    # bundle. Copy the processed media variants directly from the private upload
    # store so Chromium renders exactly what will later be published.
    copied: set[str] = set()
    for image in uploaded_images:
        variants = image.get("variants") or []
        for variant in variants:
            repo_path = str(variant.get("repo_path") or "")
            stored_path = str(variant.get("stored_path") or "")
            if not repo_path or not stored_path or repo_path in copied:
                continue
            src = Path(stored_path)
            if not src.is_file():
                continue
            target = root / repo_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            copied.add(repo_path)
        repo_path = str(image.get("repo_path") or "")
        stored_path = str(image.get("stored_path") or "")
        if repo_path and stored_path and repo_path not in copied and Path(stored_path).is_file():
            target = root / repo_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stored_path, target)
            copied.add(repo_path)


def _metric_script() -> str:
    # This script deliberately avoids pixel/image AI. It reads the rendered DOM
    # after layout has settled and checks concrete visual facts from Chromium.
    return r"""
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const root = document.documentElement;
  const visible = el => {
    if (!el) return false;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > .05 && r.width > 2 && r.height > 2;
  };
  const rectInfo = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right};
  };
  const rgb = value => {
    const m = String(value || '').match(/rgba?\((\d+)[, ]+\s*(\d+)[, ]+\s*(\d+)/i);
    return m ? [Number(m[1]),Number(m[2]),Number(m[3])] : null;
  };
  const lum = c => {
    if (!c) return null;
    const v = c.map(x => { x/=255; return x <= .03928 ? x/12.92 : Math.pow((x+.055)/1.055,2.4); });
    return .2126*v[0]+.7152*v[1]+.0722*v[2];
  };
  const contrast = (a,b) => {
    const la=lum(rgb(a)), lb=lum(rgb(b));
    if (la === null || lb === null) return null;
    return (Math.max(la,lb)+.05)/(Math.min(la,lb)+.05);
  };
  const background = el => {
    let cur = el;
    while (cur) {
      const bg = getComputedStyle(cur).backgroundColor;
      if (bg && !/rgba\([^)]*,\s*0(?:\.0+)?\)/.test(bg) && bg !== 'transparent') return bg;
      cur = cur.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor;
  };

  const h1s = [...document.querySelectorAll('h1')].filter(visible);
  const nav = [...document.querySelectorAll('nav')].find(visible) || null;
  const header = [...document.querySelectorAll('header')].find(visible) || null;
  const hero = document.querySelector('.hero') || h1s[0]?.closest('section') || h1s[0]?.parentElement || null;
  const ctas = [...document.querySelectorAll('a.button,button.button,.cta,[role="button"]')].filter(visible);
  const images = [...document.images];
  const brokenImages = images.filter(img => img.complete && img.naturalWidth === 0).map(img => img.getAttribute('src') || '').slice(0,8);
  const sections = [...document.querySelectorAll('main section')].filter(visible);
  const hugeSparse = sections.map((el,index) => {
    const r=el.getBoundingClientRect(); const text=(el.innerText||'').trim();
    const media=el.querySelectorAll('img,video,svg,canvas').length;
    return {index,height:r.height,text:text.length,media};
  }).filter(x => x.height > vh*1.8 && x.text < 180 && x.media === 0);

  const lowContrast = [];
  [...document.querySelectorAll('p,a,button,h1,h2,h3,li')].filter(visible).slice(0,180).forEach(el => {
    const s=getComputedStyle(el), ratio=contrast(s.color, background(el));
    if (ratio === null) return;
    const size=parseFloat(s.fontSize||'16'), weight=parseInt(s.fontWeight||'400',10) || 400;
    const large=size >= 24 || (size >= 18.66 && weight >= 700);
    const minimum=large ? 3 : 4.5;
    if (ratio + .05 < minimum) lowContrast.push({tag:el.tagName.toLowerCase(),text:(el.innerText||'').trim().slice(0,70),ratio:Number(ratio.toFixed(2))});
  });

  const fixedBlockers = [...document.querySelectorAll('*')].filter(el => {
    if (!visible(el)) return false;
    const s=getComputedStyle(el), r=el.getBoundingClientRect();
    return s.position === 'fixed' && r.width > vw*.65 && r.height > vh*.35;
  }).map(el => ({tag:el.tagName.toLowerCase(),cls:String(el.className||'').slice(0,90)})).slice(0,5);

  const bodyStyle=getComputedStyle(document.body);
  const bodyFont=parseFloat(bodyStyle.fontSize||'16');
  const h1Style=h1s[0] ? getComputedStyle(h1s[0]) : null;
  const navRect=rectInfo(nav), heroRect=rectInfo(hero), headerRect=rectInfo(header);
  const navOverflow = nav ? [...nav.querySelectorAll('a,button')].some(el => {
    if (!visible(el)) return false; const r=el.getBoundingClientRect(); return r.left < -2 || r.right > vw+2;
  }) : false;
  const ctaOverflow = ctas.some(el => { const r=el.getBoundingClientRect(); return r.left < -2 || r.right > vw+2 || r.width < 28 || r.height < 28; });

  return {
    viewport:{width:vw,height:vh},
    scrollWidth:root.scrollWidth,
    bodyHeight:Math.max(document.body.scrollHeight,root.scrollHeight),
    textLength:(document.body.innerText||'').trim().length,
    h1Count:h1s.length,
    h1Font:h1Style ? parseFloat(h1Style.fontSize||'0') : 0,
    h1LineHeight:h1Style ? h1Style.lineHeight : '',
    bodyFont,
    navPresent:!!nav,
    navRect,
    navOverflow,
    headerRect,
    heroPresent:!!hero,
    heroRect,
    ctaCount:ctas.length,
    ctaOverflow,
    imageCount:images.length,
    brokenImages,
    lowContrast:lowContrast.slice(0,10),
    hugeSparse,
    fixedBlockers,
    title:document.title || ''
  };
}
"""


def _issues_from_metrics(path: str, viewport: str, m: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    width = int((m.get("viewport") or {}).get("width") or 0)
    if int(m.get("scrollWidth") or 0) > width + 3:
        issues.append(_issue("high", "VISUAL_HORIZONTAL_OVERFLOW", path, f"Rendered page overflows horizontally at {viewport} width.", viewport))
    if int(m.get("textLength") or 0) < 140:
        issues.append(_issue("high", "VISUAL_PAGE_TOO_EMPTY", path, f"Rendered page contains too little visible content at {viewport}.", viewport))
    if not m.get("navPresent"):
        issues.append(_issue("high", "VISUAL_NAV_MISSING", path, f"No visible navigation rendered at {viewport}.", viewport))
    if m.get("navOverflow"):
        issues.append(_issue("high", "VISUAL_NAV_OVERFLOW", path, f"Navigation clips outside the viewport at {viewport}.", viewport))
    if not m.get("heroPresent") or int(m.get("h1Count") or 0) != 1:
        issues.append(_issue("high", "VISUAL_HERO_INVALID", path, f"Expected exactly one visible H1 inside a clear hero at {viewport}.", viewport))
    else:
        h1_font = float(m.get("h1Font") or 0)
        minimum = 30 if viewport == "mobile" else 36
        if h1_font < minimum:
            issues.append(_issue("medium", "VISUAL_H1_TOO_SMALL", path, f"Primary heading renders at only {h1_font:.0f}px on {viewport}.", viewport))
        hero_rect = m.get("heroRect") or {}
        if float(hero_rect.get("height") or 0) > float((m.get("viewport") or {}).get("height") or 1) * 1.65:
            issues.append(_issue("medium", "VISUAL_HERO_TOO_TALL", path, f"Hero is excessively tall at {viewport}, pushing useful content below the fold.", viewport))
    if float(m.get("bodyFont") or 0) < 14:
        issues.append(_issue("high", "VISUAL_BODY_TEXT_TOO_SMALL", path, f"Body typography is below 14px at {viewport}.", viewport))
    if path == "index.html" and int(m.get("ctaCount") or 0) < 1:
        issues.append(_issue("high", "VISUAL_CTA_MISSING", path, f"Homepage has no visible primary action at {viewport}.", viewport))
    if m.get("ctaOverflow"):
        issues.append(_issue("high", "VISUAL_CTA_CLIPPED", path, f"A visible call-to-action is clipped or too small at {viewport}.", viewport))
    if m.get("brokenImages"):
        issues.append(_issue("high", "VISUAL_BROKEN_IMAGE", path, f"Broken image assets rendered at {viewport}: {', '.join(m['brokenImages'][:3])}", viewport))
    if m.get("hugeSparse"):
        issues.append(_issue("medium", "VISUAL_EXCESS_EMPTY_SPACE", path, f"One or more sections create excessive empty vertical space at {viewport}.", viewport))
    if m.get("fixedBlockers"):
        issues.append(_issue("high", "VISUAL_FIXED_OVERLAY", path, f"A fixed element obscures a large part of the page at {viewport}.", viewport))
    if m.get("lowContrast"):
        sample = m["lowContrast"][0]
        issues.append(_issue("medium", "VISUAL_LOW_CONTRAST", path, f"Low text contrast detected at {viewport} (ratio {sample.get('ratio')}).", viewport))
    return issues


def _run_visual_sync(files: dict[str, Any], project_id: str, uploaded_images: list[dict[str, Any]]) -> dict[str, Any]:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    screenshot_dir = QA_ROOT / project_id / stamp
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    html_paths = sorted(path for path in files if path.endswith(".html"))[:MAX_VISUAL_PAGES]
    if not html_paths:
        return {"available": True, "passed": False, "issues": [_issue("critical", "VISUAL_NO_HTML", "", "Visual QA received no HTML pages.")], "screenshots": [], "viewports": {}}

    with tempfile.TemporaryDirectory(prefix="pv-visual-") as tmp:
        root = Path(tmp)
        _write_candidate(root, files, uploaded_images)
        handler = functools.partial(_QuietHandler, directory=str(root))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        issues: list[dict[str, str]] = []
        shots: list[dict[str, Any]] = []
        metrics_by_viewport: dict[str, list[dict[str, Any]]] = {name: [] for name in VIEWPORTS}
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    for path in html_paths:
                        for viewport, (width, height) in VIEWPORTS.items():
                            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                            page.set_default_timeout(15000)
                            try:
                                response = page.goto(f"{base}/{path}", wait_until="networkidle")
                                if response is None or response.status >= 400:
                                    issues.append(_issue("critical", "VISUAL_PAGE_LOAD_FAILED", path, f"Rendered page returned an HTTP error at {viewport}.", viewport))
                                    continue
                                page.evaluate("document.fonts && document.fonts.ready")
                                metrics = page.evaluate(_metric_script())
                                metrics_by_viewport[viewport].append({"file": path, **metrics})
                                issues.extend(_issues_from_metrics(path, viewport, metrics))
                                safe = path.replace("/", "-").replace(".html", "") or "index"
                                shot = screenshot_dir / f"{safe}-{viewport}.png"
                                page.screenshot(path=str(shot), full_page=True)
                                shots.append({"file": path, "viewport": viewport, "path": str(shot), "width": width, "height": height})
                            except Exception as exc:  # browser rendering must become a normal QA finding
                                issues.append(_issue("high", "VISUAL_RENDER_ERROR", path, f"Chromium rendering failed at {viewport}: {str(exc)[:220]}", viewport))
                            finally:
                                page.close()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            return {
                "available": False,
                "passed": False,
                "issues": [_issue("medium", "VISUAL_QA_UNAVAILABLE", "", f"Chromium visual QA is not installed or could not start: {str(exc)[:260]}")],
                "screenshots": [],
                "viewports": {},
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    # De-duplicate repeated issues that occur identically on every viewport while
    # retaining viewport-specific render defects where that detail is useful.
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in issues:
        key = (item.get("code", ""), item.get("file", ""), item.get("viewport", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    severe = sum(1 for item in unique if item.get("severity") in {"critical", "high"})
    medium = sum(1 for item in unique if item.get("severity") == "medium")
    score = max(0, 100 - severe * 18 - medium * 4)
    return {
        "available": True,
        "passed": severe == 0,
        "score": score,
        "issues": unique,
        "screenshots": shots,
        "viewports": metrics_by_viewport,
        "pages_checked": len(html_paths),
        "render_count": len(shots),
        "version": "visual-qa-v1",
    }


async def audit_files(files: dict[str, Any], project_id: str, config: dict[str, Any], uploaded_images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    del config  # reserved for future intent-aware visual rules
    return await asyncio.to_thread(_run_visual_sync, files, project_id, uploaded_images or [])
