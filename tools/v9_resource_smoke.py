#!/usr/bin/env python3
"""Offline V9 resource admission tests; no Ollama, browser, Windows or DB needed."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import resource_guard
from api import production_queue


async def verify_worker_defers_claim() -> None:
    guard = {"enabled": True, "allow_new_job": False, "available_mb": 650, "required_free_mb": 1536}
    with (
        patch.object(production_queue.resource_guard, "admission_status", return_value=guard),
        patch.object(production_queue, "_claim_next", Mock()) as claim,
    ):
        job = asyncio.create_task(production_queue._worker(0))
        try:
            await asyncio.sleep(0.06)
            assert claim.call_count == 0, "New job was claimed while RAM critically low"
        finally:
            job.cancel()
            try:
                await job
            except asyncio.CancelledError:
                pass


def verify_limits() -> None:
    snap = resource_guard.MemorySnapshot(total_mb=16000, available_mb=1100, source="test")
    with patch.object(resource_guard, "memory_snapshot", return_value=snap):
        with patch.dict(os.environ, {"PV_RESOURCE_GUARD_ENABLED": "1", "PV_MIN_FREE_RAM_MB": ""}):
            x = resource_guard.admission_status()
            assert x["required_free_mb"] == 1536
            assert not x["allow_new_job"]
        with patch.dict(os.environ, {"PV_RESOURCE_GUARD_ENABLED": "0", "PV_MIN_FREE_RAM_MB": "2500"}):
            assert resource_guard.admission_status()["allow_new_job"]
        with patch.dict(os.environ, {"PV_RESOURCE_GUARD_ENABLED": "1", "PV_MIN_FREE_RAM_MB": "invalid"}):
            assert not resource_guard.admission_status()["allow_new_job"]
    with patch.object(resource_guard, "memory_snapshot", return_value=None):
        assert resource_guard.admission_status()["allow_new_job"]
    assert resource_guard.required_free_mb(8000) == 768


def verify_launchers_and_audit() -> None:
    for path in ("start-product.ps1", "api/start-local.ps1"):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert '$env:PV_RESOURCE_GUARD_ENABLED = "1"' in source
        assert '$env:PV_MIN_FREE_RAM_MB = if ($lowMemoryProfile) { "768" } else { "1536" }' in source
        assert 'OLLAMA_FAST_KEEP_ALIVE = if ($stableMemoryProfile) { "90s" } else { "10m" }' in source
        assert 'PRODUCTION_WORKERS' in source
    audit = (ROOT / "tools/inspect-agent-host.ps1").read_text(encoding="utf-8")
    assert "Stop-Process" not in audit
    assert "CommandLine is examined" in audit
    assert "ProcessGroups" in audit


if __name__ == "__main__":
    verify_limits()
    verify_launchers_and_audit()
    asyncio.run(verify_worker_defers_claim())
    print("V9 RESOURCE SMOKE: PASS (low RAM defers jobs, overrides, no host side effects)")
