#!/usr/bin/env python3
"""Offline payment/QA integrity tests, using disposable SQLite and no Stripe charge."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException
from api import main as core
from api import billing


@contextmanager
def isolated_db():
    # Windows: transaction context does NOT close the SQLite file handle.
    conn = sqlite3.connect(core.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def audit(score: int, *, severe: bool = False) -> str:
    return json.dumps({
        "issues": [{"severity": "high", "code": "BROKEN_LINK"}] if severe else [],
        "visual_qa": {"available": True, "passed": score >= 90, "score": score},
    })


async def checks() -> None:
    assert not billing._latest_quality_approved(None)
    assert not billing._latest_quality_approved("not json")
    assert not billing._latest_quality_approved("{}")
    assert not billing._latest_quality_approved(audit(64))
    assert not billing._latest_quality_approved(audit(90, severe=True))
    assert billing._latest_quality_approved(audit(90))

    with tempfile.TemporaryDirectory(prefix="pv-v12-payment-") as directory:
        with patch.object(core, "DB_PATH", Path(directory) / "test.db"), \
             patch.object(core, "db", isolated_db), \
             patch.object(billing, "STRIPE_SECRET_KEY", "sk_test_unit_test_no_real_calls"):
            core.init_db()
            billing.ensure_billing_schema()
            with core.db() as conn:
                conn.execute(
                    "INSERT INTO users (id,email,password_hash,created_at) VALUES (?,?,?,?)",
                    ("unit-test-user", "unit-test@example.invalid", b"test-hash", core.now_iso()),
                )
                conn.execute(
                    "INSERT INTO projects (id,user_id,package,status,name,repo_name,config_json,last_audit_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("unit-test-project", "unit-test-user", "Start", "payment_pending",
                     "QA test", "generated-site-qa-check", "{}", audit(64),
                     core.now_iso(), core.now_iso()),
                )

            stripe_create = Mock(side_effect=AssertionError("Stripe must not be called for failed QA"))
            with patch.object(billing.stripe.checkout.Session, "create", stripe_create):
                try:
                    await billing.create_checkout(
                        billing.CheckoutIn(project_id="unit-test-project"),
                        user_id="unit-test-user",
                    )
                    raise AssertionError("Low-QA project was permitted to start checkout")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "QA" in str(exc.detail)
            stripe_create.assert_not_called()

            # A webhook may arrive for an *earlier* Checkout session. The paid
            # record must be preserved but publishing must never be launched.
            session = {
                "id": "cs_test_fake_unique",
                "metadata": {"project_id": "unit-test-project", "user_id": "unit-test-user", "package": "Start"},
                "payment_status": "paid",
                "payment_intent": "pi_test_fake",
                "amount_total": 49000,
                "currency": "eur",
            }
            with patch.object(core, "generate_project", side_effect=AssertionError("Must not publish")):
                await billing._mark_session_paid(session)
            with core.db() as conn:
                project = conn.execute(
                    "SELECT status FROM projects WHERE id='unit-test-project'"
                ).fetchone()
                payment = conn.execute(
                    "SELECT status FROM payments WHERE project_id='unit-test-project'"
                ).fetchone()
            assert project["status"] == "needs_review", project
            assert payment["status"] == "paid", payment


def frontend_contract() -> None:
    html = (ROOT / "dist/builder.html").read_text(encoding="utf-8")
    script = (ROOT / "dist/assets/payment-flow-v2.js").read_text(encoding="utf-8")
    assert 'assets/payment-flow-v2.js?v=20261011-v14' in html
    assert html.index("assets/builder.js?") < html.index("assets/payment-flow-v2.js?")
    assert "score >= 90" in script
    assert "QUALITY GATE" in script
    assert "Ne zaključuj plačila" in script
    assert "observedQualityApproved" in script
    assert "Plačilo še preverjam" in script


if __name__ == "__main__":
    asyncio.run(checks())
    frontend_contract()
    print("V12 PAYMENT QA: PASS (no charges, no repo operations, isolated SQLite)")
