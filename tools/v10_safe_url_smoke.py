#!/usr/bin/env python3
"""V10: no external network or local models needed to test safe product handoff."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from api import main as core


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, *, payload=None, fail=False):
        self.payload = payload or {}
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url):
        assert url.endswith("/api/tags"), url
        if self.fail:
            raise httpx.ConnectError("offline")
        return FakeResponse(self.payload)


async def test_health() -> None:
    with patch.object(core.httpx, "AsyncClient", return_value=FakeClient(fail=True)):
        missing = await core.health()
        assert missing["ok"] is True, missing
        assert missing["product"] == "project_visibility", missing
        assert missing["ollama_online"] is False, missing
        assert missing["model_ready"] is False, missing

    name = core.OLLAMA_MODEL
    with patch.object(core.httpx, "AsyncClient", return_value=FakeClient(payload={
        "models": [{"name": name}]
    })):
        live = await core.health()
        assert live["ollama_online"] is True, live
        assert live["model_installed"] is True, live
        assert live["model_ready"] is True, live

    with patch.object(core.httpx, "AsyncClient", return_value=FakeClient(payload={
        "models": [{"name": "other-model:1b"}]
    })):
        wrong = await core.health()
        assert wrong["ollama_online"] is True
        assert wrong["model_ready"] is False

    with patch.object(core.httpx, "AsyncClient", return_value=FakeClient(payload=[])):
        malformed = await core.health()
        assert malformed["ok"] and not malformed["model_installed"]


def test_safe_url_flow() -> None:
    launcher = (ROOT / "start-product.ps1").read_text(encoding="utf-8")
    assert "[switch]$LocalOnly" in launcher
    assert "[string]$PublicApiUrl" in launcher
    assert " -SkipGitHub -Model $Model -Port $Port" in launcher
    assert "trycloudflare" in launcher  # explicitly rejected, not launched
    assert "Start-Process $localBuilder" in launcher
    assert "Start-Process $stableBuilder" in launcher
    assert "tunnel --no-autoupdate" not in launcher
    assert "Start-Process -FilePath $cloudflared" not in launcher
    assert "remoteHealth.product -ne 'project_visibility'" in launcher

    runtime = (ROOT / "dist/runtime.html").read_text(encoding="utf-8")
    assert "location.replace(target)" not in runtime
    assert "location.assign('./builder.html')" in runtime
    assert "trycloudflare.com" in runtime
    assert "Odpri varen Builder" in runtime
    assert "Date.now()" in runtime

    builder = (ROOT / "dist/assets/builder.js").read_text(encoding="utf-8")
    assert "function isDisposableTunnel" in builder
    assert "if (isDisposableTunnel(location.origin))" in builder
    assert "setInterval(() =>" in builder
    assert "health.product !== 'project_visibility'" in builder
    assert "health.model_ready === true" in builder
    assert "Konfigurirano" in builder


if __name__ == "__main__":
    asyncio.run(test_health())
    test_safe_url_flow()
    print("V10 SAFE URL/HEALTH SMOKE: PASS")
