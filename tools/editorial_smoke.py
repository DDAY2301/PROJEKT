#!/usr/bin/env python3
"""Fast, read-only 10-brief editorial regression (no Ollama or deployment).

Usage: python tools/editorial_smoke.py
This exercises the real grounded planner, premium renderer and anti-duplication
checks without generating or publishing projects.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import premium_generation as premium
from api import quality_originality_v2 as quality
from api import robust_generation as robust
from tools.production_load_test import expand, payload

BLOCKERS = {
    "DUPLICATE_BODY_COPY",
    "REPEATED_SECTION_HEADING",
    "CROSS_PAGE_DUPLICATE_COPY",
    "CROSS_PAGE_NEAR_DUPLICATE_COPY",
    "CROSS_PAGE_REPEATED_HEADING",
}


def run() -> int:
    failed = 0
    for row in expand(10):
        config = payload(row)
        spec = robust._fallback_spec(config)
        pages = spec.get("pages") or []
        files = {
            ("index.html" if p["slug"] == "index" else f"{p['slug']}.html"):
                premium._render_page(config, spec, p, i)
            for i, p in enumerate(pages)
        }
        issues = quality._anti_slop_issues(files, config)
        codes = sorted({i["code"] for i in issues if i.get("code") in BLOCKERS})
        structure = [
            name for name, source in files.items()
            if not (
                "<!doctype html>" in source.lower()
                and "</html>" in source.lower()
                and "<nav" in source.lower()
                and "</nav>" in source.lower()
            )
        ]
        if len(files) < 4 or codes or structure:
            failed += 1
            print(f"FAIL: {config['name']}: blockers={codes}; bad_shell={structure}")
            # Include only QA code and affected HTML path. Customer copy is
            # deliberately not printed into shared console logs.
            for issue in issues:
                if issue.get("code") in BLOCKERS:
                    print(f"  -> {issue.get('file', '?')}: {issue.get('code')}")
        else:
            print(f"PASS: {config['name']}: {len(files)} pages; no repeated editorial blocks")
    print(f"EDITORIAL PREFLIGHT: {10 - failed}/10 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
