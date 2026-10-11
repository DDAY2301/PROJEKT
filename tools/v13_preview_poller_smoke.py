#!/usr/bin/env python3
"""V13 private preview error semantics and single builder watcher regression."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException
import api.preview as preview


class FakeResponse:
    def __init__(self, code: int, payload=None):
        self.status_code = code
        self.payload = payload or {}

    def json(self):
        return self.payload


class Client:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        assert url.endswith("/git/ref/heads/main")
        return self.response


async def check_preview_error_codes():
    for status, expected in [(404,409),(401,503),(403,503),(429,503),(502,503)]:
        with patch.object(preview.core,"github_headers",return_value={"Authorization":"Bearer test"}):
            with patch.object(preview.httpx,"AsyncClient",return_value=Client(FakeResponse(status))):
                try:
                    await preview._repo_head_sha("generated-site-unavailable")
                except HTTPException as exc:
                    assert exc.status_code == expected, (status, exc.status_code)
                else:
                    raise AssertionError("Preview unexpectedly succeeded")
    with patch.object(preview.core,"github_headers",return_value={"Authorization":"Bearer test"}):
        with patch.object(preview.httpx,"AsyncClient",return_value=Client(
            FakeResponse(200,{"object":{"sha":"a"*40}})
        )):
            assert await preview._repo_head_sha("generated-site-present") == "a"*40


def check_frontend():
    builder = (ROOT/"dist/builder.html").read_text(encoding="utf-8")
    preview_ui = (ROOT/"dist/assets/preview-email-ui.js").read_text(encoding="utf-8")
    payment = (ROOT/"dist/assets/payment-flow-v2.js").read_text(encoding="utf-8")
    server = (ROOT/"api/preview.py").read_text(encoding="utf-8")

    assert "sandbox=\"allow-scripts allow-forms\"" in preview_ui
    assert "allow-same-origin" not in preview_ui
    assert "Content-Security-Policy" in server
    assert "sandbox allow-scripts allow-forms" in server
    assert '"Referrer-Policy": "no-referrer"' in server

    assert "window.pvSyncProjectActions = syncActions" in preview_ui
    assert "window.pvSyncProjectActions?.(project)" in payment
    assert "setInterval(poll, 2500)" not in preview_ui
    assert "startPostBuildFlow" not in preview_ui
    assert "addEventListener('click', startPostBuildFlow" not in preview_ui
    assert "watchProject(" not in preview_ui
    assert "window.updateCheckoutHint = function updateCheckoutHintPostbuild" in payment
    assert "assets/payment-flow-v2.js" in builder


if __name__ == "__main__":
    asyncio.run(check_preview_error_codes())
    check_frontend()
    print("V13 PREVIEW + SINGLE WATCHER: PASS")
