#!/usr/bin/env python3
"""Offline checks for the industry-specific art direction and safe repo inventory."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.design_prompt_v3 import DESIGN_PROMPT_VERSION, select_direction, design_direction


def main() -> None:
    cases = (
        ({"name": "Northline Legal", "goal": "Advise clients about law"}, "legal"),
        ({"name": "Forest Run", "goal": "Outdoor survival courses"}, "outdoor"),
        ({"name": "DALIJA Clean", "goal": "Redno čiščenje prostorov"}, "local_service"),
        ({"name": "Atelier Grain", "goal": "Design studio commissions"}, "creative"),
        ({"name": "Relay Cloud", "goal": "SaaS workflow platform"}, "technology"),
        ({"name": "Green Roots", "goal": "Erasmus youth project"}, "social_impact"),
    )
    seen = set()
    for brief, expected in cases:
        industry, _ = select_direction(brief)
        assert industry == expected, (brief, industry, expected)
        prompt = design_direction(brief)
        assert DESIGN_PROMPT_VERSION in prompt
        assert "CTA" in prompt
        assert "fake reviews" in prompt
        assert len(prompt) < 800, len(prompt)
        seen.add(prompt)
    assert len(seen) == len(cases)

    manifest = json.loads((ROOT / "tools/generated-site-cleanup-manifest.json").read_text(encoding="utf-8"))
    names = manifest["generated_repositories"]
    assert manifest["owner"] == "DDAY2301"
    assert len(names) == 21 and len(set(names)) == 21
    assert all(x.startswith("generated-site-") for x in names)
    assert {"PROJEKT", "blog-lab"}.issubset(set(manifest["protected"]))
    assert not (set(names) & set(manifest["protected"]))
    cleanup = (ROOT / "tools/cleanup-generated-github.ps1").read_text(encoding="utf-8")
    assert "git clone --mirror" in cleanup
    assert "Invoke-RestMethod -Method Delete" in cleanup
    assert "if (-not $Execute)" in cleanup
    assert "DELETE 21 GENERATED REPOSITORIES" in cleanup

    from api import model_router
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, {"OLLAMA_EXPERT_MODELS": "too-large-expert:35b", "MODEL_ROUTING": "adaptive", "PV_EXPERT_FALLBACK_ON_FAST": "0"}):
        fast = model_router._ollama_models("fast")
        assert "too-large-expert:35b" not in fast, fast
        expert = model_router._ollama_models("expert")
        assert expert[0] == "too-large-expert:35b", expert
    print("V8 DESIGN/HOST/CLEANUP SMOKE: PASS")


if __name__ == "__main__":
    main()
