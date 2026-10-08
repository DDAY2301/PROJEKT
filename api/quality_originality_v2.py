"""Quality / Originality Gate V2 for production website output.

Adds deterministic anti-slop checks and persistent cross-site layout fingerprints
on top of the existing premium/model QA. The gate does not reward randomness:
it blocks near-identical production output while allowing a shared, tested
component library to remain consistent.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from typing import Any

from fastapi import Depends

import api.main as core
import api.robust_generation as robust_generation

_BASE_AI_AUDIT = core.ai_audit
GATE_VERSION = "quality-originality-v3"
HIGH_SIMILARITY = 0.93
MEDIUM_SIMILARITY = 0.82

SLOP_PHRASES = (
    "unlock your potential",
    "unlock the potential",
    "cutting-edge solutions",
    "innovative solutions",
    "seamless experience",
    "seamless solutions",
    "elevate your",
    "take your business to the next level",
    "in today's fast-paced",
    "redefine what's possible",
    "transform your vision",
    "tailored solutions for your unique needs",
    "empowering businesses",
    "empowering communities",
    "world-class solutions",
)


def _issue(severity: str, code: str, file: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "file": file, "message": message}


def ensure_schema() -> None:
    with core.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS design_fingerprints (
              site_key TEXT PRIMARY KEY,
              signature TEXT NOT NULL,
              motif TEXT NOT NULL,
              composition TEXT NOT NULL,
              features_json TEXT NOT NULL,
              gate_version TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )"""
        )


def _site_key(files: dict[str, Any], config: dict[str, Any]) -> str:
    manifest = files.get("assets/design-manifest.json")
    if isinstance(manifest, str):
        try:
            key = str(json.loads(manifest).get("site_key") or "").strip()
            if key:
                return key
        except Exception:
            pass
    raw = "|".join(str(config.get(k) or "").strip().lower() for k in ("organization", "name"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z][a-z0-9_-]{2,}", value.lower()) if len(x) <= 48}


def _fingerprint(files: dict[str, Any]) -> dict[str, Any]:
    index = str(files.get("index.html") or "")
    css = str(files.get("assets/site.css") or "")
    motif_match = re.search(r'data-motif="([^"]+)"', index, re.I)
    composition_match = re.search(r"\bcomposition-([a-z0-9_-]+)", index, re.I)
    section_classes = []
    for raw in re.findall(r'<section\b[^>]*class="([^"]+)"', index, re.I):
        classes = [x for x in raw.split() if x not in {"section", "reveal"}]
        section_classes.append("+".join(classes[:3]) or "section")
    css_signals = []
    for pattern in (
        r"--radius:([^;}]+)",
        r"--shell:([^;}]+)",
        r"\.hero-grid\{([^}]{0,220})\}",
        r"\.story-grid\{([^}]{0,180})\}",
        r"\.final-cta\{([^}]{0,180})\}",
    ):
        match = re.search(pattern, css, re.I | re.S)
        if match:
            css_signals.append(re.sub(r"\s+", "", match.group(1))[:220])
    features = {
        "motif": motif_match.group(1).lower() if motif_match else "",
        "composition": composition_match.group(1).lower() if composition_match else "",
        "sections": section_classes[:20],
        "css_signals": css_signals,
        "class_tokens": sorted(_tokens(" ".join(re.findall(r'class="([^"]+)"', index, re.I))))[:140],
    }
    canonical = json.dumps(features, sort_keys=True, ensure_ascii=False)
    features["signature"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return features


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if a.get("signature") and a.get("signature") == b.get("signature"):
        return 1.0
    score = 0.0
    if a.get("motif") and a.get("motif") == b.get("motif"):
        score += 0.40
    if a.get("composition") and a.get("composition") == b.get("composition"):
        score += 0.22
    score += 0.20 * _jaccard(set(a.get("sections") or []), set(b.get("sections") or []))
    score += 0.18 * _jaccard(set(a.get("css_signals") or []), set(b.get("css_signals") or []))
    return round(score, 4)


def _originality_issues(files: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    ensure_schema()
    current = _fingerprint(files)
    key = _site_key(files, config)
    best: tuple[float, str, str, str] | None = None

    with core.db() as con:
        rows = con.execute(
            """SELECT site_key,motif,composition,features_json
               FROM design_fingerprints
               WHERE site_key<>?
               ORDER BY updated_at DESC LIMIT 80""",
            (key,),
        ).fetchall()

    for row in rows:
        try:
            previous = json.loads(row["features_json"])
        except Exception:
            continue
        similarity = _similarity(current, previous)
        candidate = (similarity, str(row["site_key"]), str(row["motif"]), str(row["composition"]))
        if best is None or candidate[0] > best[0]:
            best = candidate

    issues: list[dict[str, str]] = []
    best_score = best[0] if best else 0.0
    if best and best_score >= HIGH_SIMILARITY:
        issues.append(_issue(
            "high",
            "DESIGN_NEAR_DUPLICATE",
            "index.html",
            f"Design fingerprint is {best_score:.0%} similar to another recent production site. Motif/composition must be varied before release.",
        ))
    elif best and best_score >= MEDIUM_SIMILARITY:
        issues.append(_issue(
            "medium",
            "DESIGN_SIMILARITY_WARNING",
            "index.html",
            f"Design fingerprint is {best_score:.0%} similar to another recent site; acceptable but should be watched across the batch.",
        ))

    with core.db() as con:
        con.execute(
            """INSERT INTO design_fingerprints(site_key,signature,motif,composition,features_json,gate_version,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(site_key) DO UPDATE SET
                 signature=excluded.signature,motif=excluded.motif,composition=excluded.composition,
                 features_json=excluded.features_json,gate_version=excluded.gate_version,
                 updated_at=excluded.updated_at""",
            (
                key,
                str(current.get("signature") or ""),
                str(current.get("motif") or ""),
                str(current.get("composition") or ""),
                json.dumps(current, ensure_ascii=False),
                GATE_VERSION,
                core.now_iso(),
            ),
        )

    return issues, {
        "score": round(max(0.0, 1.0 - best_score), 4),
        "nearest_similarity": round(best_score, 4),
        "nearest_site_key": best[1] if best else None,
        "motif": current.get("motif"),
        "composition": current.get("composition"),
        "signature": current.get("signature"),
    }



def _main_content_for_uniqueness(source: str) -> str:
    main = re.search(r"<main\b[^>]*>(.*?)</main>", source, re.I | re.S)
    value = main.group(1) if main else source
    # Shared discovery/CTA modules are intentionally reusable chrome and should
    # not pollute the editorial cross-page uniqueness measurement.
    value = re.sub(
        r'<section\b[^>]*class="[^"]*\b(?:related-section|final-cta)\b[^"]*"[^>]*>.*?</section>',
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", value, flags=re.I | re.S)
    return value


def _clean_visible(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip().lower()


def _copy_tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "this", "that", "from", "into", "your",
        "ter", "ali", "tudi", "smo", "kot", "pri", "naše", "nasi", "naš",
        "stran", "strani", "projekt", "projekta",
    }
    out: set[str] = set()
    for token in re.findall(r"[a-z0-9čšžćđáéíóúäöü]{3,}", value.lower(), re.UNICODE):
        if token in stop:
            continue
        # Long content words are reduced to a stable lexical stem. This catches
        # ordinary inflection/paraphrase changes such as skupina/skupinam or
        # uporabljati/uporabljajo without needing a language-specific NLP model.
        out.add(token[:6] if len(token) >= 8 else token)
    return out


def _copy_similarity(a: str, b: str) -> float:
    ta, tb = _copy_tokens(a), _copy_tokens(b)
    if len(ta) < 6 or len(tb) < 6:
        return 0.0
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def _cross_page_copy_issues(html_files: dict[str, str]) -> list[dict[str, str]]:
    paragraph_pages: dict[str, set[str]] = {}
    heading_pages: dict[str, set[str]] = {}
    paragraph_records: list[tuple[str, str]] = []

    for path, source in html_files.items():
        main = _main_content_for_uniqueness(source)
        for raw in re.findall(r"<p\b[^>]*>(.*?)</p>", main, re.I | re.S):
            text = _clean_visible(raw)
            if len(text) >= 90:
                paragraph_pages.setdefault(text, set()).add(path)
                paragraph_records.append((path, text))
        for raw in re.findall(r"<h2\b[^>]*>(.*?)</h2>", main, re.I | re.S):
            text = _clean_visible(raw)
            if len(text) >= 5:
                heading_pages.setdefault(text, set()).add(path)

    issues: list[dict[str, str]] = []
    repeated_paragraphs = [
        (text, pages) for text, pages in paragraph_pages.items() if len(pages) >= 2
    ]
    if repeated_paragraphs:
        text, pages = sorted(repeated_paragraphs, key=lambda item: (-len(item[1]), item[0]))[0]
        issues.append(_issue(
            "high",
            "CROSS_PAGE_DUPLICATE_COPY",
            sorted(pages)[0],
            f"Substantial body copy is repeated across {len(pages)} pages ({', '.join(sorted(pages)[:4])}); each page needs its own brief-grounded narrative.",
        ))

    # Catch template paraphrases, not only character-for-character copies.
    best_near: tuple[float, str, str, str, str] | None = None
    for i, (path_a, text_a) in enumerate(paragraph_records):
        for path_b, text_b in paragraph_records[i + 1:]:
            if path_a == path_b or text_a == text_b:
                continue
            similarity = _copy_similarity(text_a, text_b)
            if similarity < 0.78:
                continue
            candidate = (similarity, path_a, path_b, text_a, text_b)
            if best_near is None or candidate[0] > best_near[0]:
                best_near = candidate
    if best_near is not None:
        similarity, path_a, path_b, _text_a, _text_b = best_near
        issues.append(_issue(
            "high",
            "CROSS_PAGE_NEAR_DUPLICATE_COPY",
            path_a,
            f"Body copy on {path_a} and {path_b} is {similarity:.0%} semantically similar; each page needs a distinct brief-grounded narrative.",
        ))

    repeated_headings = [
        (text, pages) for text, pages in heading_pages.items() if len(pages) >= 3
    ]
    if repeated_headings:
        text, pages = sorted(repeated_headings, key=lambda item: (-len(item[1]), item[0]))[0]
        issues.append(_issue(
            "high",
            "CROSS_PAGE_REPEATED_HEADING",
            sorted(pages)[0],
            f'Section heading "{text[:80]}" is reused across {len(pages)} pages; this makes the site feel templated.',
        ))
    return issues


def _coverage_anchor(item: str) -> str:
    text = re.sub(r"\s+", " ", str(item or "")).strip(" -•")
    # Programme/list items commonly contain a short title followed by a
    # description. Prefer the title portion where possible.
    text = re.split(r"\s+[–—:-]\s+|[.!?]\s+", text, maxsplit=1)[0].strip()
    words = re.findall(r"[A-Za-zÀ-ž0-9]+", text, re.UNICODE)
    return " ".join(words[:5]).strip()


def _brief_coverage_issues(files: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    contexts = robust_generation._extract_page_contexts(config)
    pages = robust_generation._configured_pages(config)
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    marker_sets = {
        "program": ("Programi",),
        "galer": ("Predlagani motivi",),
        "gallery": ("Predlagani motivi",),
        "pristop": ("Ključna sporočila",),
        "approach": ("Ključna sporočila",),
        "kontakt": ("Kontaktni obrazec naj vsebuje",),
        "contact": ("Kontaktni obrazec naj vsebuje",),
    }

    for page in pages:
        slug = str(page.get("slug") or "index")
        context = contexts.get(slug, "")
        folded_slug = robust_generation._fold_text(slug)
        markers: tuple[str, ...] = ()
        for token, candidates in marker_sets.items():
            if token in folded_slug:
                markers = candidates
                break
        if not markers or not context:
            continue

        expected: list[str] = []
        for marker in markers:
            for item in robust_generation._context_items(context, marker):
                anchor = _coverage_anchor(item)
                if len(anchor) >= 3 and anchor not in expected:
                    expected.append(anchor)
        if not expected:
            continue

        path = "index.html" if slug == "index" else f"{slug}.html"
        source = str(files.get(path) or "")
        visible = _clean_visible(_main_content_for_uniqueness(source))
        found = [anchor for anchor in expected if _clean_visible(anchor) in visible]
        ratio = len(found) / len(expected) if expected else 1.0
        checks.append({
            "page": path,
            "expected": expected[:10],
            "found": found[:10],
            "coverage": round(ratio, 3),
        })
        required = 1.0 if len(expected) <= 4 else 0.75
        if ratio < required:
            missing = [anchor for anchor in expected if anchor not in found]
            issues.append(_issue(
                "high",
                "BRIEF_NAMED_CONTENT_MISSING",
                path,
                f"Only {len(found)}/{len(expected)} named brief items are present on the page. Missing: {', '.join(missing[:4])}.",
            ))

    overall = (
        sum(float(item["coverage"]) for item in checks) / len(checks)
        if checks else 1.0
    )
    return issues, {"score": round(overall, 3), "pages": checks}


def _anti_slop_issues(files: dict[str, Any], config: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    brief = json.dumps(config, ensure_ascii=False).lower()
    html_files = {p: str(v) for p, v in files.items() if p.endswith(".html")}

    hits: list[tuple[str, str]] = []
    for path, source in html_files.items():
        visible = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", source, flags=re.I | re.S)
        visible = re.sub(r"<[^>]+>", " ", visible)
        low = re.sub(r"\s+", " ", visible).lower()
        for phrase in SLOP_PHRASES:
            if phrase in low and phrase not in brief:
                hits.append((path, phrase))

        headings = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item)).strip().lower()
            for item in re.findall(r"<h2\b[^>]*>(.*?)</h2>", source, re.I | re.S)
        ]
        duplicates = sorted({h for h in headings if h and headings.count(h) > 1})
        if duplicates:
            issues.append(_issue(
                "high",
                "REPEATED_SECTION_HEADING",
                path,
                f"Repeated section heading makes the page feel templated: {duplicates[0][:90]}",
            ))

        paragraphs = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item)).strip().lower()
            for item in re.findall(r"<p\b[^>]*>(.*?)</p>", source, re.I | re.S)
        ]
        substantial = [p for p in paragraphs if len(p) >= 80]
        repeated = sorted({p for p in substantial if substantial.count(p) > 1})
        if repeated:
            issues.append(_issue(
                "high",
                "DUPLICATE_BODY_COPY",
                path,
                "The same substantial paragraph appears more than once on the page.",
            ))

    issues.extend(_cross_page_copy_issues(html_files))

    unique_hits = sorted(set(hits))
    if len(unique_hits) >= 3:
        sample = ", ".join(phrase for _, phrase in unique_hits[:3])
        issues.append(_issue("high", "AI_SLOP_DENSITY", "index.html", f"Multiple generic AI-marketing phrases detected: {sample}."))
    elif unique_hits:
        path, phrase = unique_hits[0]
        issues.append(_issue("medium", "GENERIC_MARKETING_PHRASE", path, f"Generic phrase detected and should be rewritten specifically: {phrase}."))

    index = html_files.get("index.html", "")
    if index and 'data-design-system="design-v2"' not in index.lower():
        issues.append(_issue("high", "DESIGN_ENGINE_V2_MISSING", "index.html", "Production build is not stamped by Design Engine V2."))

    return issues


async def ai_audit(files: dict[str, str], config: dict[str, Any]) -> dict[str, Any]:
    base = await _BASE_AI_AUDIT(files, config)
    issues = list(base.get("issues") or [])
    issues.extend(_anti_slop_issues(files, config))
    coverage_issues, brief_coverage = _brief_coverage_issues(files, config)
    issues.extend(coverage_issues)
    originality_issues, originality = _originality_issues(files, config)
    issues.extend(originality_issues)

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in issues:
        key = (
            str(item.get("code") or ""),
            str(item.get("file") or ""),
            str(item.get("message") or ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return {
        **base,
        "issues": unique,
        "quality_floor": GATE_VERSION,
        "originality": originality,
        "brief_coverage": brief_coverage,
    }


@core.app.get("/agent/originality")
async def originality_summary(user_id: str = Depends(core.current_user)):
    del user_id
    ensure_schema()
    with core.db() as con:
        total = con.execute("SELECT COUNT(*) AS n FROM design_fingerprints").fetchone()
        motifs = con.execute(
            "SELECT motif,COUNT(*) AS n FROM design_fingerprints GROUP BY motif ORDER BY n DESC,motif"
        ).fetchall()
        recent = con.execute(
            """SELECT site_key,motif,composition,signature,updated_at
               FROM design_fingerprints ORDER BY updated_at DESC LIMIT 20"""
        ).fetchall()
    return {
        "gate": GATE_VERSION,
        "sites_fingerprinted": int(total["n"] if total else 0),
        "motifs": {str(row["motif"]): int(row["n"]) for row in motifs},
        "recent": [dict(row) for row in recent],
    }


core.ai_audit = ai_audit
