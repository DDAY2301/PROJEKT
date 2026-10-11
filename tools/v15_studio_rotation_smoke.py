#!/usr/bin/env python3
"""V15: real 24-style CSS, brand isolation, deterministic rotation and QA contract.

Offline isolated SQLite only; no Ollama, GitHub write, customer DB or deployment.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api.main as core
import api.design_engine_v2 as engine
import api.design_prompt_v3 as director


@contextmanager
def isolated_sqlite():
    connection = sqlite3.connect(core.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


async def smoke() -> None:
    expected_names = (
        "Swiss Editorial", "Luxury Minimal", "Architectural",
        "Industrial Precision", "Automotive Performance", "Organic Nature",
        "Outdoor Editorial", "Boutique Hospitality", "Culinary Magazine",
        "Professional Legal", "Financial Trust", "Healthcare Clarity",
        "Scientific Research", "Tech Product Grid", "SaaS Utility",
        "Creative Brutalist", "Portfolio Gallery", "Artisan Craft",
        "Beauty Ritual", "Sport Kinetic", "Travel Immersive",
        "Education Pathways", "NGO Impact Story", "Event & Festival",
    )
    assert len(engine.STUDIO_TEMPLATES) == 24
    assert [name for _, name, _ in engine.STUDIO_TEMPLATES] == list(expected_names)
    assert len({name for _, _, name in engine.STUDIO_TEMPLATES}) == 24
    assert len(set(engine.MOTIFS[name]["css"] for _, _, name in engine.STUDIO_TEMPLATES)) == 24
    assert "display:none" not in engine.MOTIFS["luxury_minimal"]["css"]

    accepted_config = []
    async def planner(config):
        accepted_config.append(dict(config))
        return {"site_name":"Test Studio", "pages":[{"slug":"index","title":"Home","sections":[]}]}
    async def renderer(config, spec):
        return {
            "index.html": '<!doctype html><html lang="sl"><body class="site"><main>Real site</main></body></html>',
            "assets/site.css": "body{margin:0}",
        }

    with tempfile.TemporaryDirectory(prefix="pv-v15-studio-") as temp:
        with patch.object(core, "DB_PATH", Path(temp)/"studio.db"), \
             patch.object(core, "db", isolated_sqlite), \
             patch.object(engine, "_BASE_DESIGN_SITE", planner), \
             patch.object(engine, "_BASE_BUILD_FILES", renderer):

            all_ids = set()
            all_css = set()
            for tid, name, motif in engine.STUDIO_TEMPLATES:
                config = {
                    "_project_id": "isolated-site-" + tid,
                    "organization": "Same demo organization",
                    "name": "Same demo name",
                    "goal": "Present services",
                    "package": "Start",
                    "template_id": tid,
                    "customer_secret": "NEVER_EXPORT_THIS_STRING",
                }
                spec = await engine.design_site(config)
                design = spec["design_system"]
                assert design["template_id"] == tid
                assert design["template_name"] == name
                assert design["motif"] == motif
                assert accepted_config[-1]["_design_template_id"] == tid
                assert "_design_template_id" not in config, "Don't mutate client config"
                assert len(director.design_direction(accepted_config[-1])) < 800
                files = await engine.build_files(config, spec)
                manifest = json.loads(files["assets/design-manifest.json"])
                assert manifest["template_id"] == tid
                assert manifest["design_seed"] == design["design_seed"]
                assert "NEVER_EXPORT_THIS_STRING" not in files["assets/design-manifest.json"]
                assert motif in files["index.html"]
                assert f"motif-{motif}" in files["index.html"]
                assert len(files["assets/site.css"]) > 200
                assert motif in files["assets/site.css"]
                all_ids.add(design["design_seed"])
                all_css.add(engine._motif_css(motif, "rail"))
                assert design["fingerprint"]["design_direction"] == name
            assert len(all_ids) == 24
            assert len(all_css) == 24

            one = {"_project_id":"same-project", "name":"Wood Workshop", "goal":"handmade wooden products"}
            two = {"_project_id":"another-project", "name":"Wood Workshop", "goal":"handmade wooden products"}
            assert engine._site_key(one) != engine._site_key(two)
            result = engine._select_motif(one)
            assert result == engine._select_motif(one), "Same project should keep same layout"
            assert engine._site_key(one) != engine._site_key(two)
            retry = {**one, "_design_retry_seed": 1}
            reroll = engine._select_motif(retry)
            assert reroll[0] in engine.MOTIFS
            assert reroll[1] in engine.COMPOSITIONS
    print("V15 STUDIO-24: PASS (24 unique CSS, project isolation, real manifests, deterministic selection)")


if __name__ == "__main__":
    asyncio.run(smoke())
