"""Stripe Checkout billing for Project Visibility.

Each generated website is a one-time purchase. Prices are configured with
Stripe Price IDs in environment variables, so no amount is trusted from the
browser. The webhook is the source of truth; the success-page verification
endpoint is a safe fallback when webhook delivery is delayed.
"""

from __future__ import annotations

import asyncio
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

PACKAGE_PRICE_IDS = {
    "Start": os.getenv("STRIPE_PRICE_START", "").strip(),
    "Standard": os.getenv("STRIPE_PRICE_STANDARD", "").strip(),
    "Premium": os.getenv("STRIPE_PRICE_PREMIUM", "").strip(),
}

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
    return bool(STRIPE_SECRET_KEY and PACKAGE_PRICE_IDS.get(package))


def project_is_paid(project_id: str) -> bool:
    ensure_billing_schema()
    with core.db() as con:
        row = con.execute(
            "SELECT status FROM payments WHERE project_id=?",
            (project_id,),
        ).fetchone()
    return bool(row and row["status"] == "paid")


def payments_required(project_id: str, package: str) -> bool:
    """Require payment only once Stripe and that package price are configured.

    This keeps the local development workflow usable before the merchant has
    supplied final Price IDs, while production immediately becomes gated as
    soon as its Stripe configuration is present.
    """
    return package_is_configured(package) and not project_is_paid(project_id)


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
              stripe_session_id=COALESCE(excluded.stripe_session_id,payments.stripe_session_id),
              stripe_payment_intent=COALESCE(excluded.stripe_payment_intent,payments.stripe_payment_intent),
              amount_total=COALESCE(excluded.amount_total,payments.amount_total),
              currency=COALESCE(excluded.currency,payments.currency),
              status=excluded.status,
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
    amount_total = getattr(session, "amount_total", None) or session.get("amount_total")
    currency = getattr(session, "currency", None) or session.get("currency")
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

    with core.db() as con:
        row = con.execute("SELECT status FROM projects WHERE id=?", (project_id,)).fetchone()
    if row and row["status"] in {"queued", "awaiting_payment", "payment_pending", "failed"}:
        asyncio.create_task(core.generate_project(project_id))


@core.app.get("/billing/config")
async def billing_config():
    ensure_billing_schema()
    packages: dict[str, dict[str, Any]] = {}
    for name, price_id in PACKAGE_PRICE_IDS.items():
        item: dict[str, Any] = {"configured": bool(STRIPE_SECRET_KEY and price_id)}
        if item["configured"]:
            try:
                price = stripe.Price.retrieve(price_id)
                item.update(
                    {
                        "currency": price.get("currency"),
                        "unit_amount": price.get("unit_amount"),
                    }
                )
            except Exception:
                item["configured"] = False
        packages[name] = item
    return {
        "enabled": bool(STRIPE_SECRET_KEY),
        "packages": packages,
        "mode": "payment",
        "provider": "stripe",
    }


@core.app.post("/billing/checkout")
async def create_checkout(data: CheckoutIn, user_id: str = Depends(core.current_user)):
    ensure_billing_schema()
    with core.db() as con:
        project = con.execute(
            "SELECT id,user_id,package,name,status FROM projects WHERE id=? AND user_id=?",
            (data.project_id, user_id),
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    package = project["package"]
    price_id = PACKAGE_PRICE_IDS.get(package, "")
    if not STRIPE_SECRET_KEY or not price_id:
        raise HTTPException(503, f"Stripe price for package {package} is not configured")
    if project_is_paid(project["id"]):
        return {"paid": True, "project_id": project["id"]}

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=(
                f"{PUBLIC_BUILDER_URL}?payment=success&project_id={project['id']}"
                "&session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{PUBLIC_BUILDER_URL}?payment=cancelled&project_id={project['id']}",
            client_reference_id=project["id"],
            metadata={
                "project_id": project["id"],
                "user_id": user_id,
                "package": package,
            },
            allow_promotion_codes=True,
        )
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
            "SELECT id,package FROM projects WHERE id=? AND user_id=?",
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
        "required": package_is_configured(project["package"]),
        "paid": bool(payment and payment["status"] == "paid"),
        "payment": dict(payment) if payment else None,
    }


@core.app.post("/billing/verify/{project_id}")
async def verify_checkout(project_id: str, session_id: str, user_id: str = Depends(core.current_user)):
    ensure_billing_schema()
    with core.db() as con:
        project = con.execute(
            "SELECT id FROM projects WHERE id=? AND user_id=?",
            (project_id, user_id),
        ).fetchone()
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
