"""Stripe Checkout billing for Project Visibility.

Each generated website is a one-time purchase. The website is fully generated,
quality-checked and stored first. Stripe Checkout is offered only when that build
is ready. Successful payment then releases the existing website for publication.

Package amounts are enforced server-side and are never accepted from the browser.
The webhook is the source of truth; success-page verification is a safe fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import stripe
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

import api.main as core

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
PUBLIC_BUILDER_URL = os.getenv(
    "PUBLIC_BUILDER_URL",
    "https://dday2301.github.io/PROJEKT/builder.html",
).strip()

PACKAGE_PRICES = {
    "Start": {"unit_amount": 49000, "currency": "eur", "label": "Project Visibility — Start"},
    "Standard": {"unit_amount": 89000, "currency": "eur", "label": "Project Visibility — Standard"},
    "Premium": {"unit_amount": 149000, "currency": "eur", "label": "Project Visibility — Premium"},
}

PACKAGE_PRICE_IDS = {
    "Start": os.getenv("STRIPE_PRICE_START", "").strip(),
    "Standard": os.getenv("STRIPE_PRICE_STANDARD", "").strip(),
    "Premium": os.getenv("STRIPE_PRICE_PREMIUM", "").strip(),
}

STRIPE_AUTOMATIC_TAX = os.getenv("STRIPE_AUTOMATIC_TAX", "false").strip().lower() in {"1", "true", "yes", "on"}

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


class CheckoutIn(BaseModel):
    project_id: str


def ensure_billing_schema() -> None:
    with core.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS payments (
              project_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              package TEXT NOT NULL,
              stripe_session_id TEXT,
              stripe_payment_intent TEXT,
              amount_total INTEGER,
              currency TEXT,
              status TEXT NOT NULL DEFAULT 'unpaid',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id),
              FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )


def package_is_configured(package: str) -> bool:
    return bool(STRIPE_SECRET_KEY and package in PACKAGE_PRICES)


def project_is_paid(project_id: str) -> bool:
    ensure_billing_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT status FROM payments WHERE project_id=?",
            (project_id,),
        ).fetchone()
    return bool(row and row["status"] == "paid")


def payments_required(project_id: str, package: str) -> bool:
    """A missing Stripe key never makes a commercial package free."""
    return package in PACKAGE_PRICES and not project_is_paid(project_id)


def assert_publication_authorized(repo_name: str) -> str:
    """Fail-closed authorization for every public GitHub Pages publication path.

    Only a production-mode project with a LIVE Stripe payment, a matching
    payment record, and a passing release QA may become publicly accessible.
    Development and Stripe TEST sites stay in private preview only.
    """
    if os.getenv("PV_ENV", "development").strip().lower() != "production":
        raise RuntimeError("Public publication disabled outside PV_ENV=production")
    if not STRIPE_SECRET_KEY.startswith("sk_live_") or not STRIPE_WEBHOOK_SECRET.startswith("whsec_"):
        raise RuntimeError("Live Stripe secret and webhook verification are required for public publication")
    ensure_billing_schema()
    with core.db() as con:
        records = con.execute(
            """SELECT p.id, p.user_id, p.package, p.last_audit_json,
                      pay.user_id AS payment_user_id, pay.package AS payment_package,
                      pay.status AS payment_status, pay.stripe_session_id,
                      pay.stripe_payment_intent, pay.currency
               FROM projects AS p
               LEFT JOIN payments AS pay ON pay.project_id=p.id
               WHERE p.repo_name=?""",
            (repo_name,),
        ).fetchall()
    if len(records) != 1:
        raise RuntimeError("Public publication requires one unambiguous customer project")
    row = records[0]
    if row["package"] not in PACKAGE_PRICES:
        raise RuntimeError("Unknown commercial package; publication blocked")
    if (
        row["payment_status"] != "paid"
        or row["user_id"] != row["payment_user_id"]
        or row["package"] != row["payment_package"]
        or not str(row["stripe_session_id"] or "").startswith("cs_live_")
        or not str(row["stripe_payment_intent"] or "").startswith("pi_")
        or str(row["currency"] or "").lower() != PACKAGE_PRICES[row["package"]]["currency"]
    ):
        raise RuntimeError("A matching verified LIVE Stripe payment is required before publication")
    if not _latest_quality_approved(row["last_audit_json"]):
        raise RuntimeError("Release QA is not approved; public publication blocked")
    return str(row["id"])


def _upsert_payment(
    project_id: str,
    user_id: str,
    package: str,
    *,
    status: str,
    session_id: str | None = None,
    payment_intent: str | None = None,
    amount_total: int | None = None,
    currency: str | None = None,
) -> None:
    ensure_billing_schema()
    now = core.now_iso()
    with core.db() as con:
        con.execute(
            """
            INSERT INTO payments(
              project_id,user_id,package,stripe_session_id,stripe_payment_intent,
              amount_total,currency,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
              stripe_session_id=CASE WHEN payments.status='paid' THEN payments.stripe_session_id ELSE COALESCE(excluded.stripe_session_id,payments.stripe_session_id) END,
              stripe_payment_intent=CASE WHEN payments.status='paid' THEN payments.stripe_payment_intent ELSE COALESCE(excluded.stripe_payment_intent,payments.stripe_payment_intent) END,
              amount_total=CASE WHEN payments.status='paid' THEN payments.amount_total ELSE COALESCE(excluded.amount_total,payments.amount_total) END,
              currency=CASE WHEN payments.status='paid' THEN payments.currency ELSE COALESCE(excluded.currency,payments.currency) END,
              status=CASE WHEN payments.status='paid' THEN 'paid' ELSE excluded.status END,
              updated_at=excluded.updated_at
            """,
            (
                project_id,
                user_id,
                package,
                session_id,
                payment_intent,
                amount_total,
                currency,
                status,
                now,
                now,
            ),
        )


def _latest_quality_approved(audit_json: str | None) -> bool:
    """Recheck the actual backend release gate before collecting/releasing payment."""
    if not audit_json:
        return False
    try:
        audit = json.loads(audit_json)
    except (ValueError, TypeError):
        return False
    if not isinstance(audit, dict):
        return False
    # The audit can contain a historical quality summary. Re-evaluate the
    # current release gate instead of trusting payment/status flags alone.
    import api.enhanced_runtime as runtime
    issues = list(audit.get("issues") or [])
    visual = audit.get("visual_qa") or {}
    if not isinstance(visual, dict) or not isinstance(issues, list):
        return False
    return runtime._quality_gate_passed(issues, visual)


async def _mark_session_paid(session: Any) -> None:
    metadata = dict(getattr(session, "metadata", None) or session.get("metadata") or {})
    project_id = str(metadata.get("project_id") or "")
    user_id = str(metadata.get("user_id") or "")
    package = str(metadata.get("package") or "")
    if not project_id or not user_id or not package:
        return

    payment_status = str(getattr(session, "payment_status", None) or session.get("payment_status") or "")
    if payment_status != "paid":
        return

    session_id = str(getattr(session, "id", None) or session.get("id") or "") or None
    payment_intent = getattr(session, "payment_intent", None) or session.get("payment_intent")
    amount_total = getattr(session, "amount_total", None)
    if amount_total is None:
        amount_total = session.get("amount_total")
    currency = getattr(session, "currency", None) or session.get("currency")

    # A signed event is not sufficient on its own: the Checkout session must
    # be one that THIS API created and persisted for THIS customer/package.
    # Never let arbitrary Stripe-account sessions set project payment status.
    client_reference = getattr(session, "client_reference_id", None) or session.get("client_reference_id")
    if not session_id or client_reference != project_id:
        return
    ensure_billing_schema()
    with core.db() as con:
        current = con.execute(
            """SELECT p.user_id,p.package,p.repo_name,pay.status AS payment_status,
                      pay.stripe_session_id
               FROM projects AS p
               LEFT JOIN payments AS pay ON pay.project_id=p.id
               WHERE p.id=?""",
            (project_id,),
        ).fetchone()
    if not current or current["user_id"] != user_id or current["package"] != package:
        return
    if current["stripe_session_id"] != session_id or current["payment_status"] == "paid":
        return  # stale/foreign Checkout or duplicate delivery
    if currency != PACKAGE_PRICES.get(package, {}).get("currency"):
        return
    if amount_total is None or int(amount_total) < 0:
        return
    if os.getenv("PV_ENV", "development").strip().lower() == "production":
        if not bool(getattr(session, "livemode", None) or session.get("livemode")):
            return

    _upsert_payment(
        project_id,
        user_id,
        package,
        status="paid",
        session_id=session_id,
        payment_intent=str(payment_intent) if payment_intent else None,
        amount_total=int(amount_total) if amount_total is not None else None,
        currency=str(currency) if currency else None,
    )

    # Payment releases the ALREADY generated project. enhanced_runtime detects
    # repository_ready and publishes the existing repo without rebuilding it.
    with core.db() as con:
        row = con.execute(
            "SELECT status,last_audit_json FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if row and row["status"] in {"ready_for_payment", "payment_pending", "awaiting_payment", "failed"}:
        if not _latest_quality_approved(row["last_audit_json"]):
            # Stripe has ALREADY confirmed payment. Preserve the paid record;
            # never publish a failed QA build or charge the customer again.
            # The project must be repaired/reviewed or refunded by an operator.
            with core.db() as con:
                con.execute(
                    "UPDATE projects SET status='needs_review',updated_at=? WHERE id=?",
                    (core.now_iso(), project_id),
                )
            return
        with core.db() as con:
            transition = con.execute(
                """UPDATE projects SET status='queued',updated_at=?
                   WHERE id=? AND user_id=?
                     AND status IN ('ready_for_payment','payment_pending','awaiting_payment','failed')""",
                (core.now_iso(), project_id, user_id),
            )
        if transition.rowcount == 1:
            asyncio.create_task(core.generate_project(project_id))


def _line_item(package: str) -> dict[str, Any]:
    price_id = PACKAGE_PRICE_IDS.get(package, "")
    if price_id:
        return {"price": price_id, "quantity": 1}
    cfg = PACKAGE_PRICES[package]
    return {
        "price_data": {
            "currency": cfg["currency"],
            "unit_amount": cfg["unit_amount"],
            "product_data": {
                "name": cfg["label"],
                "description": "One-time website design, generation, QA and delivery package.",
            },
        },
        "quantity": 1,
    }


@core.app.get("/billing/config")
async def billing_config():
    ensure_billing_schema()
    packages: dict[str, dict[str, Any]] = {}
    for name, cfg in PACKAGE_PRICES.items():
        item: dict[str, Any] = {
            "configured": bool(STRIPE_SECRET_KEY),
            "currency": cfg["currency"],
            "unit_amount": cfg["unit_amount"],
        }
        price_id = PACKAGE_PRICE_IDS.get(name, "")
        if STRIPE_SECRET_KEY and price_id:
            try:
                price = stripe.Price.retrieve(price_id)
                item.update({"currency": price.get("currency"), "unit_amount": price.get("unit_amount")})
            except Exception:
                pass
        packages[name] = item
    return {
        "enabled": bool(STRIPE_SECRET_KEY),
        "packages": packages,
        "mode": "payment",
        "provider": "stripe",
        "automatic_tax": STRIPE_AUTOMATIC_TAX,
        "payment_stage": "after_build",
    }


@core.app.post("/billing/checkout")
async def create_checkout(data: CheckoutIn, user_id: str = Depends(core.current_user)):
    ensure_billing_schema()
    with core.db() as con:
        project = con.execute(
            "SELECT id,user_id,package,name,status,repo_name,last_audit_json FROM projects WHERE id=? AND user_id=?",
            (data.project_id, user_id),
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    package = project["package"]
    if not STRIPE_SECRET_KEY or package not in PACKAGE_PRICES:
        raise HTTPException(503, f"Stripe checkout for package {package} is not configured")
    if project_is_paid(project["id"]):
        return {"paid": True, "project_id": project["id"]}
    if project["status"] not in {"ready_for_payment", "payment_pending"} or not project["repo_name"]:
        raise HTTPException(409, "Website is not finished yet. Payment becomes available after build and QA.")
    if not _latest_quality_approved(project["last_audit_json"]):
        raise HTTPException(
            409,
            "Website failed its latest release QA. Payment is blocked until visual QA and critical issues are resolved.",
        )

    create_args: dict[str, Any] = {
        "mode": "payment",
        "line_items": [_line_item(package)],
        "success_url": (
            f"{PUBLIC_BUILDER_URL}?payment=success&project_id={project['id']}"
            "&session_id={CHECKOUT_SESSION_ID}"
        ),
        "cancel_url": f"{PUBLIC_BUILDER_URL}?payment=cancelled&project_id={project['id']}",
        "client_reference_id": project["id"],
        "metadata": {
            "project_id": project["id"],
            "user_id": user_id,
            "package": package,
        },
        "allow_promotion_codes": True,
        "billing_address_collection": "auto",
    }
    if STRIPE_AUTOMATIC_TAX:
        create_args["automatic_tax"] = {"enabled": True}

    try:
        session = stripe.checkout.Session.create(**create_args, idempotency_key=f"pv-checkout-{project['id']}")
    except Exception as exc:
        raise HTTPException(502, f"Could not create Stripe Checkout session: {str(exc)[:300]}") from exc

    _upsert_payment(
        project["id"],
        user_id,
        package,
        status="pending",
        session_id=session.id,
    )
    with core.db() as con:
        con.execute(
            "UPDATE projects SET status='payment_pending',updated_at=? WHERE id=?",
            (core.now_iso(), project["id"]),
        )
    return {"checkout_url": session.url, "session_id": session.id, "project_id": project["id"]}


@core.app.get("/billing/project/{project_id}")
async def payment_status(project_id: str, user_id: str = Depends(core.current_user)):
    ensure_billing_schema()
    with core.db() as con:
        project = con.execute(
            "SELECT id,package,status,repo_name FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
        payment = con.execute(
            "SELECT status,amount_total,currency,stripe_session_id FROM payments WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    return {
        "project_id": project_id,
        "package": project["package"],
        "required": project["package"] in PACKAGE_PRICES,
        "ready_for_payment": bool(project["status"] in {"ready_for_payment", "payment_pending"} and project["repo_name"]),
        "paid": bool(payment and payment["status"] == "paid"),
        "payment": dict(payment) if payment else None,
    }


@core.app.post("/billing/verify/{project_id}")
async def verify_checkout(project_id: str, session_id: str, user_id: str = Depends(core.current_user)):
    ensure_billing_schema()
    with core.db() as con:
        project = con.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe is not configured")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as exc:
        raise HTTPException(502, "Could not verify Stripe Checkout session") from exc
    metadata = dict(session.get("metadata") or {})
    if metadata.get("project_id") != project_id or metadata.get("user_id") != user_id:
        raise HTTPException(403, "Checkout session does not belong to this project")
    await _mark_session_paid(session)
    return {"paid": project_is_paid(project_id), "project_id": project_id}


@core.app.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Stripe webhook secret is not configured")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except ValueError as exc:
        raise HTTPException(400, "Invalid Stripe payload") from exc
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(400, "Invalid Stripe signature") from exc

    if event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        await _mark_session_paid(event["data"]["object"])
    return {"received": True}
