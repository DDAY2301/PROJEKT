#!/usr/bin/env python3
"""V17 fail-closed publication tests. Disposable DB; no network or charges."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import billing, billing_gate, enhanced_runtime, main as core, pages_publish


@contextmanager
def isolated_db():
    connection = sqlite3.connect(core.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def approved_audit() -> str:
    return json.dumps({
        "issues": [],
        "repository_ready": True,
        "public_live": False,
        "visual_qa": {"available": True, "passed": True, "score": 92},
    })


def blocked(repo: str) -> None:
    try:
        billing.assert_publication_authorized(repo)
    except RuntimeError:
        return
    raise AssertionError("Unverified or unpaid project was allowed to publish")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pv-v17-release-") as directory:
        with patch.object(core, "DB_PATH", Path(directory) / "v17-test.db"), \
             patch.object(core, "db", isolated_db), \
             patch.object(billing, "STRIPE_SECRET_KEY", ""), \
             patch.object(billing, "STRIPE_WEBHOOK_SECRET", ""), \
             patch.dict(os.environ, {"PV_ENV": "production", "PV_ALLOW_TEST_PAYMENT_BYPASS": "0"}):
            core.init_db()
            billing.ensure_billing_schema()
            with core.db() as con:
                con.execute(
                    "INSERT INTO users (id,email,password_hash,created_at) VALUES(?,?,?,?)",
                    ("test-user", "customer@example.invalid", b"x", core.now_iso()),
                )
                con.execute(
                    "INSERT INTO users (id,email,password_hash,created_at) VALUES(?,?,?,?)",
                    ("test-bypass", "maj@klemec.org", b"x", core.now_iso()),
                )
                con.execute(
                    """INSERT INTO projects
                       (id,user_id,package,status,name,repo_name,config_json,last_audit_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    ("test-project", "test-user", "Start", "ready_for_payment",
                     "V17 test", "generated-site-v17-test", "{}", approved_audit(),
                     core.now_iso(), core.now_iso()),
                )
            repo = "generated-site-v17-test"
            assert billing.payments_required("test-project", "Start"), "Missing Stripe must not mean free"
            blocked(repo)
            # The shared publisher must reject before even preparing GitHub credentials.
            with patch.object(core, "github_headers", side_effect=AssertionError("Network call attempted")):
                try:
                    await pages_publish.publish_generated_site(repo)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Public publisher allowed missing Stripe")

            # Merely providing a TEST key never enables public publication.
            with patch.object(billing, "STRIPE_SECRET_KEY", "sk_test_fake"):
                blocked(repo)
                assert not billing_gate.sandbox_payment_bypass("test-bypass")
                with patch.dict(os.environ, {"PV_ENV": "test", "PV_ALLOW_TEST_PAYMENT_BYPASS": "1"}):
                    assert billing_gate.sandbox_payment_bypass("test-bypass")
                    blocked(repo)  # Even a TEST-only bypass must not publish publicly.

            with patch.object(billing, "STRIPE_SECRET_KEY", "sk_live_fake_for_unit_tests"), \
                 patch.object(billing, "STRIPE_WEBHOOK_SECRET", "whsec_fake_for_unit_tests"):
                blocked(repo)  # Unpaid even with production keys.
                with core.db() as con:
                    con.execute(
                        """INSERT INTO payments
                           (project_id,user_id,package,stripe_session_id,stripe_payment_intent,
                            amount_total,currency,status,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        ("test-project", "test-user", "Start",
                         "cs_live_fake_for_unit_tests", "pi_fake_for_unit_tests",
                         49000, "eur", "paid", core.now_iso(), core.now_iso()),
                    )
                assert billing.assert_publication_authorized(repo) == "test-project"
                with core.db() as con:
                    con.execute("UPDATE payments SET stripe_session_id='cs_test_fake' WHERE project_id='test-project'")
                blocked(repo)
                with core.db() as con:
                    con.execute("UPDATE payments SET stripe_session_id='cs_live_fake_for_unit_tests' WHERE project_id='test-project'")
                    con.execute("UPDATE projects SET last_audit_json=? WHERE id='test-project'",
                                (json.dumps({"issues": [{"severity": "high"}], "visual_qa": {"available": True, "passed": True, "score": 95}}),))
                blocked(repo)
                with core.db() as con:
                    con.execute("UPDATE projects SET last_audit_json=? WHERE id='test-project'", (approved_audit(),))
                    row = con.execute("SELECT * FROM projects WHERE id='test-project'").fetchone()

                # A successful GitHub API publish with an unreachable URL is NOT ready.
                fake_public_url = "https://example.invalid/generated-site-v17-test/"
                with patch.object(enhanced_runtime, "publish_generated_site", new_callable=AsyncMock) as pub, \
                     patch.object(enhanced_runtime, "wait_for_generated_site", new_callable=AsyncMock) as live:
                    pub.return_value = fake_public_url
                    live.return_value = False
                    await enhanced_runtime._publish_existing_project(
                        "test-project", row, json.loads(approved_audit())
                    )
                    pub.assert_awaited_once()
                    live.assert_awaited_once()
                with core.db() as con:
                    result = con.execute(
                        "SELECT status,last_audit_json FROM projects WHERE id='test-project'"
                    ).fetchone()
                audit = json.loads(result["last_audit_json"])
                assert result["status"] == "needs_review", result["status"]
                assert audit["public_live"] is False
                assert audit["public_url"] == fake_public_url

    print("V17 COMMERCIAL RELEASE GATES: PASS (offline, no Stripe charge, no GitHub changes)")


if __name__ == "__main__":
    asyncio.run(main())
