#!/usr/bin/env python3
"""Read-only V7 policy and low-memory startup regression without Ollama.

Run: python tools/v7_policy_smoke.py
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from api import main as core
from api import model_router as router

ROOT = Path(__file__).resolve().parents[1]


async def check_routed_calls() -> None:
    candidate = router.Candidate("ollama", "test-local-model", "http://127.0.0.1:11434")
    fake_response = AsyncMock(return_value='{"ok":true}')
    choose = Mock(return_value=[candidate])
    with (
        patch.object(router, "_candidates", choose),
        patch.object(router, "_ollama_generate", fake_response),
        patch.object(router, "_record"),
        patch.dict(os.environ, {"PV_AGENT_V7_ENABLED": "1"}),
    ):
        result = await router.generate(
            "Build a grounded site for a repair shop.",
            "Return JSON only.",
            json_mode=True,
            num_predict=50,
        )
        assert result == '{"ok":true}'
        assert choose.call_args.kwargs["system"] == "Return JSON only."
        received = fake_response.await_args.args[3]
        assert "Project Visibility V7 policy:" in received
        assert "Never invent testimonials" in received
        assert "Return JSON only." in received
        assert received.count("Project Visibility V7 policy:") == 1
        assert (await core.health())["agent_policy"] == "V7"

    fake_response.reset_mock()
    with (
        patch.object(router, "_candidates", return_value=[candidate]),
        patch.object(router, "_ollama_generate", fake_response),
        patch.object(router, "_record"),
        patch.dict(os.environ, {"PV_AGENT_V7_ENABLED": "off"}),
    ):
        await router.generate("Simple input", "Return HTML only.", num_predict=50)
        assert fake_response.await_args.args[3] == "Return HTML only."
        assert (await core.health())["agent_policy"] == "disabled"


def check_ram_profile() -> None:
    for name in ("start-product.ps1", "api/start-local.ps1"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert '$lowMemoryProfile = $systemRamGB -gt 0 -and $systemRamGB -le 12' in source
        assert '$autoWorkers = if ($lowMemoryProfile) { "1" } else { "4" }' in source
        assert '$autoVisualConcurrency = if ($lowMemoryProfile) { "1" } else { "2" }' in source
        assert '$autoLoadedModels = if ($lowMemoryProfile) { "1" } else { "2" }' in source
        assert 'if (-not $env:PRODUCTION_WORKERS)' in source
        assert 'if (-not $env:MODEL_CONCURRENCY)' in source
        assert 'if (-not $env:PV_AGENT_V7_ENABLED)' in source


if __name__ == "__main__":
    assert router.AGENT_POLICY_VERSION == "V7"
    assert (ROOT / "AGENTS.md").is_file()
    asyncio.run(check_routed_calls())
    check_ram_profile()
    print("V7 POLICY SMOKE: PASS (routing, rollback toggle, health, 8GB defaults)")
