"""Design Engine V2: deterministic motif selection and art-direction layer.

The language model plans content. This module owns visual identity. It selects a
stable motif from a curated production library, avoids recently over-used
motifs, stamps the chosen system into the deliverable, and applies deterministic
CSS composition overrides on top of the proven premium renderer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from fastapi import Depends

import api.main as core

_BASE_DESIGN_SITE = core.design_site
_BASE_BUILD_FILES = core.build_files
ENGINE_VERSION = "design-v2"
COMPOSITIONS = ("offset", "centered", "rail", "stacked")

MOTIFS: dict[str, dict[str, Any]] = {
    "swiss_editorial": {
        "keywords": ("editorial", "swiss", "institution", "project", "research", "architecture"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "0px", "shell": "1320px", "tracking": "-.07em",
        "css": """.site-header{background:rgba(248,248,244,.94);border-color:#1c2722}.brand,.nav-links a{color:var(--ink)}.menu span{background:var(--ink)}
.hero{background:var(--bg);color:var(--ink);border-bottom:1px solid var(--ink)}.hero::after{display:none}.hero-grid{grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);align-items:end}.label-light,.hero-copy p,.text-link{color:var(--ink)}.hero-copy h1{text-transform:none}.visual{box-shadow:none;border:1px solid var(--ink);background:#fff}.section{border-bottom:1px solid var(--line)}.story-card{border-radius:0}.final-cta{background:var(--ink)}""",
    },
    "luxury_minimal": {
        "keywords": ("luxury", "premium", "beauty", "fashion", "jewelry", "consulting"),
        "font": 'Inter,Arial,sans-serif', "display": 'Georgia,"Times New Roman",serif',
        "radius": "8px", "shell": "1160px", "tracking": "-.035em",
        "css": """.site-header{background:rgba(22,20,17,.88)}.hero{background:linear-gradient(135deg,#171512,#29241f);}.hero::after{opacity:.28}.hero-grid{grid-template-columns:1fr;text-align:center;max-width:1050px}.hero-copy,.hero-copy p{margin-left:auto;margin-right:auto}.hero-art{display:none}.hero-actions{justify-content:center}.section-head h2,.hero-copy h1{font-family:var(--display)}.section-head{max-width:850px}.story-card{background:#211d19}.button{border-radius:2px}.final-cta{text-align:center;background:#171512}""",
    },
    "outdoor_field": {
        "keywords": ("outdoor", "nature", "survival", "forest", "adventure", "camp", "environment"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "18px", "shell": "1280px", "tracking": "-.065em",
        "css": """.hero{background:linear-gradient(145deg,#071b12,var(--primary) 66%,#142015)}.hero-grid{grid-template-columns:minmax(0,.9fr) minmax(420px,1.1fr)}.visual{transform:rotate(1.2deg);background:linear-gradient(155deg,#d9d1ae,#879b75)}.visual-grid{background-size:72px 72px}.section:nth-of-type(even){background:#eef0e7!important}.story-card{background:#10251b}.final-cta{background:linear-gradient(120deg,#10251b,var(--primary))}""",
    },
    "corporate_grid": {
        "keywords": ("corporate", "finance", "legal", "b2b", "industry", "company"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "10px", "shell": "1260px", "tracking": "-.05em",
        "css": """.hero{background:linear-gradient(135deg,#07121f,var(--primary))}.hero-grid{grid-template-columns:1fr 1fr}.visual{border:1px solid rgba(255,255,255,.18);box-shadow:none}.section{padding:92px 0}.intro-grid,.section-split{gap:70px}.story-grid{gap:1px;background:var(--line);border:1px solid var(--line)}.story-card{border:0;border-radius:0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px}.final-cta{background:#07121f}""",
    },
    "creative_brutal": {
        "keywords": ("creative", "culture", "art", "music", "studio", "festival", "youth"),
        "font": 'Arial,Helvetica,sans-serif', "display": 'Arial Black,Arial,sans-serif',
        "radius": "0px", "shell": "1380px", "tracking": "-.06em",
        "css": """.site-header{background:#000;border-bottom:3px solid var(--accent)}.hero{background:var(--accent);color:#050505}.hero::after{display:none}.hero-grid{grid-template-columns:1.2fr .8fr}.label-light,.hero-copy p,.text-link{color:#050505}.button-accent{background:#000;color:#fff;border-radius:0}.visual{border:4px solid #000;border-radius:0;box-shadow:12px 12px 0 #000;background:#fff}.section{border-bottom:3px solid #000}.section-head h2,.hero-copy h1{text-transform:uppercase}.story-card{border:3px solid var(--accent);border-radius:0}.final-cta{background:#000}""",
    },
    "tech_precision": {
        "keywords": ("tech", "software", "saas", "ai", "data", "digital", "platform", "engineering"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "14px", "shell": "1240px", "tracking": "-.06em",
        "css": """.site-header{background:rgba(4,11,18,.9)}.hero{background:#050b12}.hero::before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px);background-size:32px 32px}.hero-grid{grid-template-columns:minmax(0,1fr) minmax(380px,.8fr)}.visual{background:#081723;color:#e7fff4;border:1px solid color-mix(in srgb,var(--accent) 50%,transparent);box-shadow:0 30px 80px rgba(0,0,0,.45)}.label{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.section-ink{background:#050b12}.final-cta{background:#050b12}""",
    },
    "organic_story": {
        "keywords": ("organic", "community", "food", "wellbeing", "green", "sustainable", "craft"),
        "font": 'Inter,Arial,sans-serif', "display": 'Georgia,"Times New Roman",serif',
        "radius": "42px", "shell": "1180px", "tracking": "-.035em",
        "css": """.hero{background:linear-gradient(145deg,var(--primary),#243426)}.hero-grid{grid-template-columns:.9fr 1.1fr}.visual{border-radius:48% 52% 46% 54%/45% 45% 55% 55%;background:linear-gradient(145deg,#eee6cf,#cbd7bd)}.section-head h2,.hero-copy h1{font-family:var(--display)}.section{padding:120px 0}.story-card{border-radius:34px}.button{border-radius:999px}.final-cta{border-radius:42px 42px 0 0}""",
    },
    "automotive_dark": {
        "keywords": ("car", "auto", "automotive", "vehicle", "detailing", "motorsport", "garage"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "4px", "shell": "1360px", "tracking": "-.075em",
        "css": """.site-header{background:rgba(3,5,7,.92)}.hero{background:linear-gradient(105deg,#030507 0%,#111820 54%,var(--primary) 140%)}.hero-grid{grid-template-columns:1.05fr .95fr;min-height:820px}.hero-copy h1{text-transform:uppercase;font-style:italic}.visual{border-radius:4px;background:linear-gradient(145deg,#202830,#090c10);color:#fff}.visual-grid{opacity:.35}.section-ink,.final-cta{background:#05070a}.story-card{border-radius:4px;background:#0b0f13}.button{border-radius:3px}""",
    },
    "hospitality_warm": {
        "keywords": ("hotel", "restaurant", "travel", "tourism", "wellness", "spa", "hospitality"),
        "font": 'Inter,Arial,sans-serif', "display": 'Georgia,"Times New Roman",serif',
        "radius": "24px", "shell": "1160px", "tracking": "-.035em",
        "css": """.site-header{background:rgba(60,38,25,.88)}.hero{background:linear-gradient(145deg,#4b3020,#7c543a)}.hero-grid{grid-template-columns:1fr;text-align:center;max-width:1050px}.hero-copy,.hero-copy p{margin-inline:auto}.hero-actions{justify-content:center}.hero-art{max-width:820px;width:100%;margin:auto}.section-head h2,.hero-copy h1{font-family:var(--display)}.section:nth-of-type(even){background:#f3eadf!important}.story-card{background:#4b3020}.final-cta{background:#4b3020}""",
    },
    "ngo_story": {
        "keywords": ("ngo", "erasmus", "youth", "project", "social", "community", "education"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "26px", "shell": "1220px", "tracking": "-.055em",
        "css": """.hero{background:linear-gradient(135deg,var(--primary),#102a25)}.hero-grid{grid-template-columns:minmax(0,1fr) minmax(340px,.8fr)}.visual{background:linear-gradient(145deg,#fff7df,#d9e8dc)}.intro-grid{grid-template-columns:.7fr 1.3fr}.section-head h2{max-width:900px}.story-card{background:#102a25}.metric-band{border-block:1px solid rgba(0,0,0,.15)}.final-cta{background:var(--primary)}""",
    },
    "local_service": {
        "keywords": ("cleaning", "repair", "service", "local", "salon", "clinic", "trade", "servis", "čiščenje"),
        "font": 'Inter,Arial,sans-serif', "display": 'Inter,Arial,sans-serif',
        "radius": "16px", "shell": "1180px", "tracking": "-.05em",
        "css": """.hero{background:linear-gradient(120deg,var(--primary),#0b2821)}.hero-grid{grid-template-columns:1.1fr .9fr;min-height:680px}.hero-copy h1{font-size:clamp(52px,6.2vw,92px)}.section{padding:82px 0}.intro-grid,.section-split{gap:52px}.story-card{min-height:430px}.button-accent{box-shadow:none}.final-cta{background:var(--primary)}""",
    },
    "magazine": {
        "keywords": ("magazine", "news", "story", "blog", "media", "publishing", "journal"),
        "font": 'Inter,Arial,sans-serif', "display": 'Georgia,"Times New Roman",serif',
        "radius": "0px", "shell": "1280px", "tracking": "-.04em",
        "css": """.site-header{background:rgba(255,255,255,.95);border-bottom:2px solid var(--ink)}.brand,.nav-links a{color:var(--ink)}.menu span{background:var(--ink)}.hero{background:#fff;color:var(--ink);border-bottom:5px solid var(--ink)}.hero::after{display:none}.hero-grid{grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);align-items:end}.label-light,.hero-copy p,.text-link{color:var(--ink)}.hero-copy h1,.section-head h2{font-family:var(--display)}.section{border-bottom:1px solid var(--ink)}.story-grid{grid-template-columns:2fr 1fr 1fr}.story-card{border-radius:0;background:#111}.final-cta{background:#111}""",
    },
}


def _ensure_history() -> None:
    with core.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS design_motif_history (
              site_key TEXT PRIMARY KEY,
              motif TEXT NOT NULL,
              composition TEXT NOT NULL,
              engine_version TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )"""
        )


def _site_key(config: dict[str, Any]) -> str:
    raw = "|".join(str(config.get(k) or "").strip().lower() for k in ("organization", "name"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _brief_text(config: dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, sort_keys=True).lower()


def _candidate_score(name: str, profile: dict[str, Any], text: str) -> int:
    score = sum(4 for kw in profile.get("keywords", ()) if kw in text)
    if name.replace("_", " ") in text:
        score += 12
    return score


def _select_motif(config: dict[str, Any]) -> tuple[str, str]:
    _ensure_history()
    key = _site_key(config)
    retry_seed = max(0, min(3, int(config.get("_design_retry_seed") or 0)))
    existing_motif = ""
    existing_composition = ""
    with core.db() as con:
        existing = con.execute(
            "SELECT motif,composition FROM design_motif_history WHERE site_key=?",
            (key,),
        ).fetchone()
        if existing and existing["motif"] in MOTIFS:
            existing_motif = str(existing["motif"])
            existing_composition = str(existing["composition"])
            if retry_seed == 0:
                return existing_motif, existing_composition
        rows = con.execute(
            "SELECT motif,composition FROM design_motif_history ORDER BY updated_at DESC LIMIT 120"
        ).fetchall()

    usage = Counter(str(row["motif"]) for row in rows)
    text = _brief_text(config)
    scored = {name: _candidate_score(name, profile, text) for name, profile in MOTIFS.items()}
    best_score = max(scored.values(), default=0)
    if best_score:
        ranked = sorted(scored, key=lambda name: (-scored[name], name))
        relevant = [name for name in ranked if scored[name] >= max(1, best_score - 4)]
        pool = relevant[:4]
        if len(pool) < 3:
            pool = ranked[:3]
    else:
        pool = list(MOTIFS)
    if retry_seed and existing_motif in pool and len(pool) > 1:
        pool = [name for name in pool if name != existing_motif]

    minimum_use = min((usage[name] for name in pool), default=0)
    least_used = [name for name in pool if usage[name] == minimum_use]

    digest = hashlib.sha256((key + f"|retry:{retry_seed}|" + text[:4000]).encode("utf-8")).hexdigest()
    motif = sorted(least_used)[int(digest[:8], 16) % len(least_used)]
    combo_usage = Counter(
        str(row["composition"])
        for row in rows
        if str(row["motif"]) == motif and str(row["composition"]) in COMPOSITIONS
    )
    minimum_combo_use = min((combo_usage[name] for name in COMPOSITIONS), default=0)
    least_used_compositions = [name for name in COMPOSITIONS if combo_usage[name] == minimum_combo_use]
    if retry_seed and motif == existing_motif and existing_composition in least_used_compositions and len(least_used_compositions) > 1:
        least_used_compositions = [name for name in least_used_compositions if name != existing_composition]
    composition = sorted(least_used_compositions)[int(digest[8:16], 16) % len(least_used_compositions)]

    with core.db() as con:
        now = core.now_iso()
        con.execute(
            """INSERT INTO design_motif_history(site_key,motif,composition,engine_version,created_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(site_key) DO UPDATE SET
                 motif=excluded.motif,composition=excluded.composition,
                 engine_version=excluded.engine_version,updated_at=excluded.updated_at""",
            (key, motif, composition, ENGINE_VERSION, now, now),
        )
    return motif, composition


def _composition_css(composition: str) -> str:
    return {
        "offset": ".composition-offset .hero-art{transform:translateY(34px)}.composition-offset .intro-grid{grid-template-columns:.75fr 1.25fr}",
        "centered": ".composition-centered .hero-grid{text-align:center}.composition-centered .hero-copy,.composition-centered .hero-copy p{margin-inline:auto}.composition-centered .hero-actions{justify-content:center}.composition-centered .hero-art{max-width:860px;width:100%;margin-inline:auto}",
        "rail": ".composition-rail .hero-grid{grid-template-columns:minmax(260px,.55fr) minmax(0,1.45fr)}.composition-rail .hero-copy{order:2}.composition-rail .hero-art{order:1}.composition-rail .intro-grid{grid-template-columns:1.35fr .65fr}",
        "stacked": ".composition-stacked .hero-grid{grid-template-columns:1fr}.composition-stacked .hero-art{max-width:980px;width:100%}.composition-stacked .section-split{grid-template-columns:1fr}.composition-stacked .prose{max-width:900px}",
    }.get(composition, "")


def _motif_css(motif: str, composition: str) -> str:
    profile = MOTIFS[motif]
    return f"""
/* {ENGINE_VERSION}: {motif} / {composition} */
:root{{--radius:{profile['radius']};--shell:{profile['shell']};--font:{profile['font']};--display:{profile['display']};--display-tracking:{profile['tracking']}}}
body{{font-family:var(--font)}}.hero-copy h1,.section-head h2{{font-family:var(--display);letter-spacing:var(--display-tracking)}}
{profile['css']}
{_composition_css(composition)}
@media(max-width:980px){{.hero-grid{{grid-template-columns:1fr}}.composition-rail .hero-grid{{grid-template-columns:1fr}}.composition-rail .hero-copy,.composition-rail .hero-art{{order:initial}}}}
@media(max-width:760px){{.composition-centered .hero-grid{{text-align:left}}.composition-centered .hero-actions{{justify-content:flex-start}}}}
"""


def _stamp_html(source: str, motif: str, composition: str) -> str:
    source = re.sub(
        r"<html\b",
        f'<html data-design-system="{ENGINE_VERSION}" data-motif="{motif}"',
        source,
        count=1,
        flags=re.I,
    )
    return re.sub(
        r'<body\s+class="([^"]*)"',
        lambda m: f'<body class="{m.group(1)} motif-{motif} composition-{composition}"',
        source,
        count=1,
        flags=re.I,
    )


async def design_site(config: dict[str, Any]) -> dict[str, Any]:
    spec = await _BASE_DESIGN_SITE(config)
    motif, composition = _select_motif(config)
    spec["design_system"] = {
        "version": ENGINE_VERSION,
        "motif": motif,
        "composition": composition,
    }
    return spec


async def build_files(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, str]:
    design = spec.get("design_system") if isinstance(spec.get("design_system"), dict) else {}
    motif = str(design.get("motif") or "")
    composition = str(design.get("composition") or "")
    if motif not in MOTIFS or composition not in COMPOSITIONS:
        motif, composition = _select_motif(config)
        spec["design_system"] = {"version": ENGINE_VERSION, "motif": motif, "composition": composition}

    files = await _BASE_BUILD_FILES(config, spec)
    css = str(files.get("assets/site.css") or "")
    files["assets/site.css"] = css + "\n" + _motif_css(motif, composition)
    for path, source in list(files.items()):
        if path.endswith(".html") and isinstance(source, str):
            files[path] = _stamp_html(source, motif, composition)

    files["assets/design-manifest.json"] = json.dumps(
        {
            "engine": ENGINE_VERSION,
            "motif": motif,
            "composition": composition,
            "site_key": _site_key(config),
        },
        ensure_ascii=False,
        indent=2,
    )
    return files


@core.app.get("/agent/design-engine")
async def design_engine_status(user_id: str = Depends(core.current_user)):
    del user_id
    return motif_summary()


def motif_summary() -> dict[str, Any]:
    _ensure_history()
    with core.db() as con:
        rows = con.execute(
            "SELECT motif,COUNT(*) AS n FROM design_motif_history GROUP BY motif ORDER BY n DESC,motif"
        ).fetchall()
    return {
        "engine": ENGINE_VERSION,
        "motifs": sorted(MOTIFS),
        "compositions": list(COMPOSITIONS),
        "usage": {str(row["motif"]): int(row["n"]) for row in rows},
    }


core.design_site = design_site
core.build_files = build_files
