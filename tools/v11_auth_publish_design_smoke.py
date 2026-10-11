#!/usr/bin/env python3
"""V11 offline integration checks: local auth, publishing mode and art direction."""
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

import jwt
from fastapi import HTTPException

from api import main as core
from api import design_prompt_v3 as design


@contextmanager
def _test_db():
    """Make transaction semantics explicit AND close handles before temp cleanup.

    sqlite3.Connection.__exit__ commits/rolls back but does not close() the
    connection. Windows refuses to unlink an open SQLite file (WinError 32).
    This wrapper is for the test only: no production schema or DB is modified.
    """
    con = sqlite3.connect(core.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


async def check_auth() -> None:
    # Never touch the operator's app-secret file, users or production SQLite DB.
    # Patch the DB accessor so every test-only connection is closed promptly.
    with patch.object(core, "db", _test_db):
        with tempfile.TemporaryDirectory(prefix="pv-v11-auth-") as temp:
            isolated = Path(temp) / "temporary_auth.db"
            with patch.object(core, "DB_PATH", isolated):
                core.init_db()
                created = await core.register(core.RegisterIn(
                    email="test-login@example.com", password="Test-Only-Password-123"
                ))
                assert isinstance(created["token"], str)
                claims = jwt.decode(created["token"], core.APP_SECRET, algorithms=["HS256"])
                user_id = core.current_user(authorization="Bearer " + created["token"])
                assert claims["sub"] == user_id
                assert (await core.active_session(user_id=user_id)) == {"authenticated": True}
                signed_in = await core.login(core.LoginIn(
                    email="TEST-LOGIN@example.com", password="Test-Only-Password-123"
                ))
                assert isinstance(signed_in["token"], str)
                try:
                    await core.login(core.LoginIn(
                        email="test-login@example.com", password="Incorrect-Password-123"
                    ))
                    raise AssertionError("Wrong password was accepted")
                except HTTPException as exc:
                    assert exc.status_code == 401

                # Recreate the isolated DB from scratch: old JWT must not
                # automatically count as a logged-in account on a new database.
                with patch.object(core, "DB_PATH", Path(temp) / "fresh.db"):
                    core.init_db()
                    try:
                        await core.active_session(user_id=user_id)
                        raise AssertionError("Token from previous DB was trusted")
                    except HTTPException as exc:
                        assert exc.status_code == 401


def check_launcher_and_frontend() -> None:
    launcher = (ROOT / "start-product.ps1").read_text(encoding="utf-8")
    assert "[switch]$LocalOnly" in launcher
    assert "[switch]$EnablePublishing" in launcher
    assert 'if ($EnablePublishing)' in launcher
    assert "& $localScript -Model $Model -Port $Port" in launcher
    assert "& $localScript -SkipGitHub -Model $Model -Port $Port" in launcher
    assert "Start-Process $localBuilder" in launcher
    assert "trycloudflare.com" in launcher

    client = (ROOT / "dist/assets/builder.js").read_text(encoding="utf-8")
    assert "function saveSession(value)" in client
    assert "function clearSession()" in client
    assert "verifyExistingSession()" in client
    assert "request('/auth/session')" in client
    assert "pv_token_api_url" in client
    assert "installPublishingCheck()" in client
    assert "request('/agent/preflight')" in client


def check_design() -> None:
    assert design.DESIGN_PROMPT_VERSION == "art-direction-v4"
    samples = [
        {"name": "Northline Legal", "goal": "law consulting"},
        {"name": "Forest Run", "goal": "outdoor training"},
        {"name": "DALIJA Clean", "goal": "čiščenje stanovanj"},
        {"name": "Relay Cloud", "goal": "SaaS operations"},
    ]
    for brief in samples:
        direction = design.design_direction(brief)
        execution = design.render_direction(brief, {"slug": "storitve", "purpose": "present services"})
        assert "Compositional motif" in direction
        assert "fake reviews" in direction
        assert "Page=storitve" in execution
        assert "accessible" in direction
        assert len(direction) < 800, len(direction)
        assert len(execution) < 1150, len(execution)
        assert direction == design.design_direction(brief), "Art direction must be deterministic"
    code = (ROOT / "api/robust_generation.py").read_text(encoding="utf-8")
    assert code.count("design_prompt_v3.render_direction(config") >= 2


if __name__ == "__main__":
    asyncio.run(check_auth())
    check_launcher_and_frontend()
    check_design()
    print("V11 AUTH/PUBLISH/DESIGN: PASS (isolated DB and deterministic offline tests)")
