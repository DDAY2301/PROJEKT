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
    # Model-generated page meta can be identical even when all section bodies
    # are unique. The ordinary fallback-only check above cannot catch this.
    # Exercise the final renderer with a realistic shared hero description.
    config = payload(expand(10)[1])
    spec = robust._fallback_spec(config)
    if len(spec["pages"]) >= 3:
        shared = (
            "A carefully assembled introduction to the organization and its work "
            "that could appear unchanged across several model-planned pages "
            "unless the renderer checks other pages before selecting hero copy."
        )
        spec["pages"][1]["meta_description"] = shared
        spec["pages"][2]["meta_description"] = shared
        first = premium._hero_lead(config, spec, spec["pages"][1])
        second = premium._hero_lead(config, spec, spec["pages"][2])
        collision_files = {
            ("index.html" if p["slug"] == "index" else f"{p['slug']}.html"):
                premium._render_page(config, spec, p, i)
            for i, p in enumerate(spec["pages"])
        }
        collisions = {
            issue["code"] for issue in quality._cross_page_copy_issues(collision_files)
        }
        if shared in (first, second) or "CROSS_PAGE_DUPLICATE_COPY" in collisions:
            failed += 1
            print(f"FAIL: model-planned shared hero description: {sorted(collisions)}")
        else:
            print("PASS: model-planned shared hero description is not repeated")
    else:
        failed += 1
        print("FAIL: insufficient pages for shared-hero regression")

    # Forest Run regression: a local planning model can reuse one long
    # sentence inside two *different* multi-sentence section bodies, and also
    # reuse the homepage hero inside a course-page paragraph. Both cases used
    # to escape whole-body duplicate checks but failed rendered cross-page QA.
    config = payload(expand(10)[1])
    shared_hero = (
        "A practical outdoor education programme that introduces field methods "
        "through guided exploration and clear preparation for each new setting."
    )
    shared_detail = (
        "Every field exercise starts with careful observation of the terrain "
        "and gives participants an opportunity to explain what they have learned."
    )
    config["hero_subtitle"] = shared_hero
    spec = robust._fallback_spec(config)
    home = next(p for p in spec["pages"] if p["slug"] == "index")
    courses = next(p for p in spec["pages"] if p["slug"] == "tecaji")
    home["sections"] = [
        {"type": "intro", "heading": "About Forest Run",
         "body": home["purpose"]},
        {"type": "method", "heading": "Practical field experience",
         "body": shared_detail + " Each outdoor visit also has a clear learning purpose."},
        {"type": "audience", "heading": "Visitors and participants",
         "body": "The programme addresses people who want to explore outdoor skills through practical experience."},
    ]
    courses["sections"] = [
        {"type": "intro", "heading": "How the courses work",
         "body": shared_hero + " Lessons are organized by the subjects named on this page."},
        {"type": "format", "heading": "From observation to practice",
         "body": shared_detail + " Each course also introduces a different practical topic."},
        {"type": "decision", "heading": "Choosing a course",
         "body": courses["purpose"]},
    ]
    contexts = robust._extract_page_contexts(config)
    spec["pages"] = robust._enforce_plan_uniqueness(spec["pages"], config, contexts)
    files = {
        ("index.html" if p["slug"] == "index" else f"{p['slug']}.html"):
            premium._render_page(config, spec, p, i)
        for i, p in enumerate(spec["pages"])
    }
    leftovers = [i for i in quality._cross_page_copy_issues(files)
                 if i["code"] in BLOCKERS]
    if leftovers or shared_hero in files["tecaji.html"] or shared_detail in files["tecaji.html"]:
        failed += 1
        print("FAIL: Forest Run partial-paragraph duplication across index.html and tecaji.html")
    else:
        print("PASS: Forest Run homepage/course long-paragraph overlap")
    print(f"EDITORIAL PREFLIGHT: {12 - failed}/12 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
