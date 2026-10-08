#!/usr/bin/env python3
"""Read-only QA blocker diagnosis for a completed Project Visibility load test.

The benchmark JSON intentionally contains no full project content. Recover the
issue *codes* from the local SQLite project audits without exporting customer
briefs, secrets, file contents, or issue messages.

Example:
  python tools/diagnose_load_test.py --results load-test-results/20261008-091533
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "api" / "data" / "agent.db"


def safe_code(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or "UNKNOWN"))[:80]
    return cleaned.upper() or "UNKNOWN"


def inspect(results_dir: Path, db_path: Path) -> tuple[list[dict], Counter]:
    projects = json.loads((results_dir / "projects.json").read_text(encoding="utf-8-sig"))
    if not isinstance(projects, list):
        raise ValueError("projects.json must contain a list")
    if not db_path.is_file():
        raise FileNotFoundError(f"Local SQLite database not found: {db_path}")

    rows: list[dict] = []
    affected: Counter = Counter()
    # SQLite is opened in read-only mode; no project state is changed.
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as con:
        for project in projects:
            project_id = str(project.get("project_id") or "")
            record = con.execute(
                "SELECT status,last_audit_json FROM projects WHERE id=?",
                (project_id,),
            ).fetchone() if project_id else None
            if record:
                try:
                    audit = json.loads(record[1] or "{}")
                except (ValueError, TypeError):
                    audit = {}
                issues = audit.get("issues") or []
                blockers = Counter(
                    safe_code(issue.get("code"))
                    for issue in issues
                    if isinstance(issue, dict)
                    and str(issue.get("severity") or "").lower() in {"critical", "high"}
                )
                affected.update(blockers.keys())
                # Export page filenames only, never QA messages or customer copy.
                # Cross-page issues name both pages in their diagnostic message.
                blocker_pages: dict[str, set[str]] = {}
                for issue in issues:
                    if not isinstance(issue, dict) or str(issue.get("severity") or "").lower() not in {"critical", "high"}:
                        continue
                    code = safe_code(issue.get("code"))
                    names = re.findall(
                        r"(?<![\\w.-])[A-Za-z0-9_.-]+\\.html\\b",
                        str(issue.get("message") or "") + " " + str(issue.get("file") or ""),
                        re.I,
                    )
                    blocker_pages.setdefault(code, set()).update(names)
                row = {
                    "blocker_pages": {code: sorted(names) for code, names in blocker_pages.items()},
                    "name": str(project.get("name") or "Unnamed"),
                    "status": str(record[0] or ""),
                    "blockers": dict(blockers.most_common()),
                    "quality_gate_passed": audit.get("quality_gate_passed"),
                    "available": True,
                }
            else:
                row = {
                    "name": str(project.get("name") or "Unnamed"),
                    "status": str(project.get("status") or ""),
                    "blockers": {},
                    "blocker_pages": {},
                    "quality_gate_passed": None,
                    "available": False,
                }
            rows.append(row)
    return rows, affected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path, help="Load-test result directory")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("DB_PATH", str(DEFAULT_DB))))
    args = parser.parse_args()

    rows, affected = inspect(args.results, args.db)
    lines = [
        "# Load test: actual critical/high blocker codes",
        "",
        f"Projects in report: {len(rows)}",
        f"Projects matched in local DB: {sum(r['available'] for r in rows)}",
        "",
        "## Blockers by affected project count",
    ]
    if affected:
        lines.extend(f"- {code}: {count}" for code, count in affected.most_common())
    else:
        lines.append("- No blockers found in available database audits.")
    lines.extend(["", "## Individual projects"])
    for row in rows:
        codes = ", ".join(f"{code} ({count})" for code, count in row["blockers"].items()) or "none recorded"
        prefix = "" if row["available"] else " [NOT FOUND IN DB]"
        lines.append(f"- {row['name']}: {row['status']}; blockers: {codes}{prefix}")
        for code, pages in row["blocker_pages"].items():
            if pages:
                lines.append(f"  - {code} affected HTML: {', '.join(pages)}")
    lines.extend([
        "",
        "Codes are taken from the last stored audit for each project.",
        "Only blocker codes and HTML filenames are exported; no customer source, brief, prompt, issue message, or token is exported.",
    ])
    report = "\n".join(lines) + "\n"
    output = args.results / "BLOCKERS.md"
    output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved: {output}")
    return 0 if all(row["available"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
