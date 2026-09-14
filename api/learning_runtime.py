"""Persistent, versioned operational learning for Project Visibility.

The agent does not rewrite its own source code. Instead it persists generic
quality lessons in SQLite, loads them into every future design prompt, records
which project/audit state produced each lesson, and exposes a monotonically
increasing learned-runtime version. Approved source upgrades still come from the
GitHub repository, which the launcher updates before every start.

Customer copy, images, passwords, emails and other project content are never
stored as learning lessons.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter

from fastapi import Depends

import api.main as core

_base_design_site = core.design_site
_base_generate_project = core.generate_project
BASE_AGENT_VERSION = "PV-2"
SOURCE_COMMIT = os.getenv("PV_SOURCE_COMMIT", "unknown").strip() or "unknown"

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
    "VISUAL_OVERFLOW": "Prevent horizontal overflow at desktop, tablet and mobile widths before publication.",
    "VISUAL_WEAK_HERO": "Use deliberate hero hierarchy, spacing and media composition rather than a generic first section.",
    "VISUAL_EMPTY_SPACE": "Avoid accidental large blank regions; whitespace must support hierarchy and rhythm.",
    "VISUAL_BROKEN_IMAGE": "Never release a layout with missing, distorted or incorrectly cropped project media.",
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
            CREATE TABLE IF NOT EXISTS agent_learning_runs (
              project_id TEXT PRIMARY KEY,
              fingerprint TEXT NOT NULL,
              learned_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_state (
              id INTEGER PRIMARY KEY CHECK(id=1),
              generation INTEGER NOT NULL DEFAULT 0,
              last_project_id TEXT,
              last_learning_at TEXT,
              source_commit TEXT NOT NULL DEFAULT 'unknown'
            );
            INSERT OR IGNORE INTO agent_state(id,generation,source_commit) VALUES(1,0,'unknown');
            """
        )
        con.execute("UPDATE agent_state SET source_commit=? WHERE id=1", (SOURCE_COMMIT,))


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


def _state() -> dict:
    ensure_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT generation,last_project_id,last_learning_at,source_commit FROM agent_state WHERE id=1"
        ).fetchone()
    generation = int(row["generation"] or 0) if row else 0
    return {
        "version": f"{BASE_AGENT_VERSION}.{generation:04d}",
        "generation": generation,
        "last_project_id": row["last_project_id"] if row else None,
        "last_learning_at": row["last_learning_at"] if row else None,
        "source_commit": row["source_commit"] if row else SOURCE_COMMIT,
    }


def _memory(limit: int = 10) -> list[str]:
    ensure_schema()
    with core.db() as con:
        rows = con.execute(
            "SELECT key,occurrences,guidance FROM agent_learning WHERE kind='issue' ORDER BY occurrences DESC,last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [f"{row['guidance']} (observed {row['occurrences']}x)" for row in rows if row["guidance"]]


def _fingerprint(status: str, audit_json: str, attempts: int) -> str:
    raw = f"{status}|{attempts}|{audit_json or ''}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()


def record_project(project_id: str) -> None:
    ensure_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT package,status,config_json,last_audit_json,auto_fix_attempts FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
    if not row or row["status"] not in {"ready", "needs_review", "failed", "ready_for_payment"}:
        return

    fingerprint = _fingerprint(str(row["status"]), str(row["last_audit_json"] or ""), int(row["auto_fix_attempts"] or 0))
    with core.db() as con:
        learned = con.execute("SELECT fingerprint FROM agent_learning_runs WHERE project_id=?", (project_id,)).fetchone()
    if learned and learned["fingerprint"] == fingerprint:
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

    severe = any(str(x.get("severity")) in {"critical", "high"} for x in issues)
    if row["status"] in {"ready", "ready_for_payment"} and not severe:
        page_count = len(config.get("pages") or [])
        _upsert(
            f"SUCCESS:{row['package']}:{page_count}",
            "success",
            f"Successful {row['package']} build with {page_count} page(s) and {int(row['auto_fix_attempts'] or 0)} repair cycle(s).",
        )

    now = core.now_iso()
    with core.db() as con:
        con.execute(
            """
            INSERT INTO agent_learning_runs(project_id,fingerprint,learned_at) VALUES(?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET fingerprint=excluded.fingerprint,learned_at=excluded.learned_at
            """,
            (project_id, fingerprint, now),
        )
        con.execute(
            "UPDATE agent_state SET generation=generation+1,last_project_id=?,last_learning_at=?,source_commit=? WHERE id=1",
            (project_id, now, SOURCE_COMMIT),
        )


async def design_site_with_memory(config: dict):
    enriched = dict(config)
    memory = _memory()
    state = _state()
    enriched["_agent_runtime"] = {
        "version": state["version"],
        "source_commit": state["source_commit"],
        "last_project_id": state["last_project_id"],
        "purpose": "Continue from persistent generic quality learning accumulated by earlier completed builds.",
    }
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


@core.app.get("/agent/state")
async def agent_state(user_id: str = Depends(core.current_user)):
    del user_id
    state = _state()
    state["lessons"] = _memory(12)
    return state


core.design_site = design_site_with_memory
core.generate_project = generate_project_with_learning
