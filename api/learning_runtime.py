"""Persistent operational learning for Project Visibility.

This is deliberately not autonomous source-code mutation. The agent records
anonymous build-quality signals (issue codes, package, page count, fix count)
and feeds recurring, generic lessons back into future planning prompts. Customer
copy, images, emails and other project content are not stored in the learning
memory.
"""

from __future__ import annotations

import json
from collections import Counter

from fastapi import Depends

import api.main as core

_base_design_site = core.design_site
_base_generate_project = core.generate_project

GUIDANCE = {
    "RAW_LANGUAGE_MARKER": "Never emit raw language labels such as html or css before actual file content.",
    "HTML_SHELL_INVALID": "Every page must be a complete HTML5 document with doctype, main content and closing html tag.",
    "STYLESHEET_MISSING": "Every HTML page must load the shared assets/site.css design system.",
    "PLACEHOLDER_LINK": "Never publish placeholder href=# links; every interactive link needs a real destination.",
    "LAYOUT_CHROME_MISSING": "Keep a consistent header, navigation and footer on every page.",
    "UNSUPPORTED_CONTACT_FACT": "Never invent phone numbers or contact facts that are not supplied in the brief.",
    "UNSUPPORTED_ADDRESS": "Never invent a physical address that is not supplied in the brief.",
    "DESIGN_SYSTEM_TOO_THIN": "Use the premium design system with sufficient responsive, layout and component depth.",
    "DESIGN_SYSTEM_MISSING": "Preserve responsive media queries, focus states, brand variables, site header and hero primitives.",
    "INVALID_FONT": "Use system-safe or explicitly provided fonts only; never reference an unavailable font.",
    "FIXED_FOOTER": "Do not use a fixed footer that can obscure content.",
    "HOME_TOO_SHALLOW": "A premium homepage needs a complete narrative, not just a hero and one content block.",
    "HERO_MISSING": "Every homepage needs one strong, designed hero with a single primary heading.",
    "VIEWPORT_MISSING": "Always include responsive viewport metadata.",
    "BUILD_FAILED": "Prefer deterministic fallbacks and bounded retries over failing an entire customer build.",
    "REVISION_FAILED": "Preserve working files and apply focused revisions rather than rebuilding unrelated parts.",
}


def ensure_schema() -> None:
    with core.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_learning (
              key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              occurrences INTEGER NOT NULL DEFAULT 1,
              guidance TEXT NOT NULL,
              last_seen TEXT NOT NULL
            );
            """
        )


def _upsert(key: str, kind: str, guidance: str) -> None:
    ensure_schema()
    with core.db() as con:
        row = con.execute("SELECT occurrences FROM agent_learning WHERE key=?", (key,)).fetchone()
        if row:
            con.execute(
                "UPDATE agent_learning SET occurrences=?,guidance=?,last_seen=? WHERE key=?",
                (int(row["occurrences"]) + 1, guidance[:500], core.now_iso(), key),
            )
        else:
            con.execute(
                "INSERT INTO agent_learning(key,kind,occurrences,guidance,last_seen) VALUES(?,?,?,?,?)",
                (key, kind, 1, guidance[:500], core.now_iso()),
            )


def _memory(limit: int = 8) -> list[str]:
    ensure_schema()
    with core.db() as con:
        rows = con.execute(
            "SELECT key,occurrences,guidance FROM agent_learning WHERE kind='issue' ORDER BY occurrences DESC,last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [f"{row['guidance']} (observed {row['occurrences']}x)" for row in rows if row["guidance"]]


def record_project(project_id: str) -> None:
    with core.db() as con:
        row = con.execute(
            "SELECT package,status,config_json,last_audit_json,auto_fix_attempts FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
    if not row:
        return
    try:
        config = json.loads(row["config_json"] or "{}")
    except Exception:
        config = {}
    try:
        audit = json.loads(row["last_audit_json"] or "{}")
    except Exception:
        audit = {}

    issues = [x for x in (audit.get("issues") or []) if isinstance(x, dict)]
    counts = Counter(str(x.get("code") or "UNKNOWN") for x in issues)
    for code, count in counts.items():
        guidance = GUIDANCE.get(code)
        if not guidance:
            sample = next((str(x.get("message") or "") for x in issues if str(x.get("code") or "UNKNOWN") == code), "")
            guidance = f"Avoid recurring quality issue {code}: {sample[:280]}" if sample else f"Avoid recurring quality issue {code}."
        for _ in range(max(1, count)):
            _upsert(f"ISSUE:{code}", "issue", guidance)

    if row["status"] in {"ready", "needs_review"} and not any(str(x.get("severity")) in {"critical", "high"} for x in issues):
        page_count = len(config.get("pages") or [])
        _upsert(
            f"SUCCESS:{row['package']}:{page_count}",
            "success",
            f"Successful {row['package']} build with {page_count} page(s) and {int(row['auto_fix_attempts'] or 0)} repair cycle(s).",
        )


async def design_site_with_memory(config: dict):
    enriched = dict(config)
    memory = _memory()
    if memory:
        enriched["_quality_memory"] = {
            "purpose": "Recurring generic lessons from earlier builds. Treat these as hard quality guidance, never as customer content.",
            "lessons": memory,
        }
    return await _base_design_site(enriched)


async def generate_project_with_learning(project_id: str):
    try:
        return await _base_generate_project(project_id)
    finally:
        try:
            record_project(project_id)
        except Exception:
            # Learning must never be able to break a customer build.
            pass


@core.app.get("/agent/learning")
async def learning_summary(user_id: str = Depends(core.current_user)):
    del user_id
    ensure_schema()
    with core.db() as con:
        rows = con.execute(
            "SELECT key,kind,occurrences,guidance,last_seen FROM agent_learning ORDER BY occurrences DESC,last_seen DESC LIMIT 30"
        ).fetchall()
    return [dict(row) for row in rows]


core.design_site = design_site_with_memory
core.generate_project = generate_project_with_learning
