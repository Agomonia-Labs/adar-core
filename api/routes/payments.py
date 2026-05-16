"""
api/routes/payments.py — Stripe payments for all domains.

Domain routing:
  DOMAIN=geetabitan → single plan: Adar Geetabitan Standard ($3.99/mo, 14-day trial)
  DOMAIN=arcl       → three plans: Basic / Standard / Unlimited

Both domains share the same endpoints. Plan config is resolved at runtime
from DOMAIN env var and the appropriate STRIPE_PRICE_* secret.
"""
from __future__ import annotations
import os, time
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routes.auth import get_current_team

router = APIRouter(prefix="/api/payments", tags=["payments"])

# ── Stripe globals ─────────────────────────────────────────────────────────────
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
DOMAIN           = os.getenv("DOMAIN", "arcl")
TEAMS_COLLECTION = "adar_teams"   # must match auth.py
FRONTEND_URL   = os.getenv("FRONTEND_URL", "")


# ── Domain-specific plan catalogue ────────────────────────────────────────────
def _plan_catalogue() -> dict:
    if DOMAIN == "geetabitan":
        return {
            "standard": {
                "name":        "Adar Geetabitan Standard",
                "price_id":    os.getenv("STRIPE_PRICE_GEETABITAN", ""),
                "trial_days":  14,
                "quota":       200,
                "description": "$3.99/month · 14-day free trial",
            },
        }
    return {
        "basic": {
            "name":        "ARCL Basic",
            "price_id":    os.getenv("STRIPE_PRICE_BASIC", ""),
            "trial_days":  14,
            "quota":       50,
            "description": "Basic plan",
        },
        "standard": {
            "name":        "ARCL Standard",
            "price_id":    os.getenv("STRIPE_PRICE_STANDARD", ""),
            "trial_days":  14,
            "quota":       200,
            "description": "Standard plan",
        },
        "unlimited": {
            "name":        "ARCL Unlimited",
            "price_id":    os.getenv("STRIPE_PRICE_UNLIMITED", ""),
            "trial_days":  14,
            "quota":       1000,
            "description": "Unlimited plan",
        },
    }


def _get_plan(plan_key: str):
    catalogue = _plan_catalogue()
    if plan_key not in catalogue:
        plan_key = next(iter(catalogue))
    return catalogue[plan_key], plan_key


def _frontend_url() -> str:
    if FRONTEND_URL:
        return FRONTEND_URL.rstrip("/")
    return "https://geetabitan.adar.agomoniai.com" if DOMAIN == "geetabitan" else "https://arcl.agomoniai.com"


def _fs_update(team_id: str, updates: dict):
    """Sync Firestore upsert — creates document if it doesn't exist."""
    from google.cloud import firestore
    db  = firestore.Client(database=os.getenv("AUTH_FIRESTORE_DATABASE", "(default)"))
    ref = db.collection(TEAMS_COLLECTION).document(team_id)
    # set(merge=True) creates the doc if missing, updates fields if it exists
    ref.set(updates, merge=True)


async def _update_team(team_id: str, updates: dict):
    """Run sync Firestore update from async FastAPI handler."""
    import asyncio, logging
    if not team_id:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _fs_update, team_id, updates)
        logging.info(f"[Firestore] Updated team={team_id} updates={updates}")
    except Exception as e:
        logging.error(f"[Firestore] Update failed for {team_id}: {e}")
        raise


# ── Create checkout session ───────────────────────────────────────────────────
class CheckoutRequest(BaseModel):
    plan: str = "standard"


@router.post("/create-checkout")
async def create_checkout(req: CheckoutRequest, team: dict = Depends(get_current_team)):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    plan_cfg, plan_key = _get_plan(req.plan)
    if not plan_cfg["price_id"]:
        raise HTTPException(500, f"Stripe price not configured for plan '{plan_key}'")

    team_id    = team["team_id"]
    team_email = team.get("email", "")

    try:
        customer_id = team.get("stripe_customer_id")
        if not customer_id:
            customer    = stripe.Customer.create(
                email=team_email,
                metadata={"team_id": team_id, "domain": DOMAIN},
            )
            customer_id = customer.id
            try:
                await _update_team(team_id, {"stripe_customer_id": customer_id})
            except Exception as db_err:
                import logging
                logging.warning(f"Could not save stripe_customer_id: {db_err}")

        base    = _frontend_url()
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": plan_cfg["price_id"], "quantity": 1}],
            mode="subscription",
            subscription_data={
                "trial_period_days": int(plan_cfg["trial_days"]),
                "metadata": {"team_id": team_id, "domain": DOMAIN, "plan": plan_key},
            },
            success_url=f"{base}?payment=success",
            cancel_url= f"{base}?payment=cancelled",
            metadata={"team_id": team_id, "domain": DOMAIN, "plan": plan_key},
        )
        return {"url": session.url, "checkout_url": session.url}

    except stripe.StripeError as e:
        raise HTTPException(400, str(e.user_message or e))
    except Exception as e:
        raise HTTPException(500, f"Checkout error: {str(e)}")


# ── Billing portal ────────────────────────────────────────────────────────────
@router.post("/portal")
async def billing_portal(team: dict = Depends(get_current_team)):
    customer_id = team.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found")
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=_frontend_url())
    return {"url": session.url, "portal_url": session.url}


# ── Billing info ──────────────────────────────────────────────────────────────
@router.get("/billing")
async def get_billing(team: dict = Depends(get_current_team)):
    catalogue   = _plan_catalogue()
    customer_id = team.get("stripe_customer_id")
    if not customer_id:
        return {"status": "inactive", "domain": DOMAIN}
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="all", limit=1)
        if not subs.data:
            return {"status": "inactive", "domain": DOMAIN}
        sub      = subs.data[0]
        plan_key = sub.get("metadata", {}).get("plan", "standard")
        trial_end = sub.get("trial_end")
        trial_days = max(0, int((trial_end - time.time()) / 86400)) if trial_end and trial_end > time.time() else None
        next_date  = datetime.utcfromtimestamp(sub["current_period_end"]).isoformat() if sub.get("current_period_end") else None
        # Fetch invoices
        invoices = []
        try:
            inv_list = stripe.Invoice.list(customer=customer_id, limit=10)
            for inv in inv_list.data:
                if inv.get("amount_paid", 0) > 0 or inv.get("amount_due", 0) > 0:
                    invoices.append({
                        "id":       inv["id"],
                        "date":     datetime.utcfromtimestamp(inv["created"]).strftime("%b %d, %Y"),
                        "amount":   (inv.get("amount_paid") or inv.get("amount_due", 0)) / 100,
                        "currency": inv.get("currency", "usd").upper(),
                        "status":   inv.get("status", ""),
                        "pdf_url":  inv.get("invoice_pdf", ""),
                    })
        except stripe.StripeError:
            pass

        trial_end_date = None
        if trial_end and trial_end > time.time():
            trial_end_date = datetime.utcfromtimestamp(trial_end).strftime("%Y-%m-%d")

        return {
            # New field names
            "status":               sub["status"],
            "domain":               DOMAIN,
            "plan":                 plan_key,
            "plan_name":            catalogue.get(plan_key, {}).get("name", plan_key),
            "trial_days_remaining": trial_days,
            "next_billing_date":    next_date,
            "cancel_at_period_end": sub.get("cancel_at_period_end", False),
            # Legacy field names (Billing.jsx compatibility)
            "subscription_status":  sub["status"],
            "subscription_plan":    plan_key,
            "trial_end_date":       trial_end_date,
            "trial_ends_at":        trial_end_date,
            "subscription_ends_at": next_date,
            "invoices":             invoices,
            "usage_today":          0,   # populated by caller if needed
            "daily_quota":          catalogue.get(plan_key, {}).get("quota", 200),
        }
    except stripe.StripeError as e:
        raise HTTPException(500, str(e))


# ── Plan catalogue (public) ───────────────────────────────────────────────────
@router.get("/plans")
async def get_plans():
    """Return plans for Checkout.jsx. Uses hardcoded amounts — no Stripe call needed."""
    if DOMAIN == "geetabitan":
        return {
            "domain": "geetabitan",
            "plans": [{
                "id":          "standard",
                "name":        "Adar Geetabitan Standard",
                "description": "$3.99/month · 14-day free trial",
                "amount":      399,
                "currency":    "USD",
                "interval":    "month",
            }],
        }
    # ARCL — three plans with hardcoded amounts
    return {
        "domain": "arcl",
        "plans": [
            {"id": "basic",     "name": "ARCL Basic",
             "description": "Basic plan",
             "amount": 0, "currency": "USD", "interval": "month"},
            {"id": "standard",  "name": "ARCL Standard",
             "description": "Standard plan",
             "amount": 0, "currency": "USD", "interval": "month"},
            {"id": "unlimited", "name": "ARCL Unlimited",
             "description": "Unlimited plan",
             "amount": 0, "currency": "USD", "interval": "month"},
        ],
    }


# ── Activate ──────────────────────────────────────────────────────────────────
@router.post("/activate")
async def activate(team: dict = Depends(get_current_team)):
    """Called after Stripe payment success. Updates team status to active."""
    import logging
    team_id  = team.get("team_id", "")
    plan_key = team.get("subscription_plan", "standard")

    if not team_id:
        raise HTTPException(400, "Missing team_id")

    try:
        await _update_team(team_id, {
            "status":            "active",
            "subscription_plan": plan_key,
        })
        return {"status": "activated", "plan": plan_key, "team_id": team_id}
    except Exception as e:
        raise HTTPException(500, f"Activation error: {str(e)}")


# ── Stripe webhook (handles both domains) ────────────────────────────────────
@router.post("/cancel")
async def cancel_subscription(team: dict = Depends(get_current_team)):
    """Cancel at period end."""
    customer_id = team.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found")
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            subs = stripe.Subscription.list(customer=customer_id, status="trialing", limit=1)
        if not subs.data:
            raise HTTPException(404, "No active subscription found")
        stripe.Subscription.modify(subs.data[0].id, cancel_at_period_end=True)
        return {"message": "Subscription will cancel at end of billing period."}
    except stripe.StripeError as e:
        raise HTTPException(500, str(e))


@router.post("/reactivate")
async def reactivate_subscription(team: dict = Depends(get_current_team)):
    """Undo cancel_at_period_end."""
    customer_id = team.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found")
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            raise HTTPException(404, "No active subscription found")
        stripe.Subscription.modify(subs.data[0].id, cancel_at_period_end=False)
        return {"message": "Subscription reactivated successfully."}
    except stripe.StripeError as e:
        raise HTTPException(500, str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook")

    etype = event["type"]
    obj   = event["data"]["object"]

    async def _update(team_id: str, updates: dict):
        await _update_team(team_id, updates)

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        meta     = obj.get("metadata", {})
        plan_key = meta.get("plan", "standard")
        status   = obj.get("status")
        updates  = {"subscription_plan": plan_key}
        if status in ("active", "trialing"):  updates["status"] = "active"
        elif status in ("canceled", "unpaid", "past_due"): updates["status"] = "suspended"
        await _update(meta.get("team_id", ""), updates)

    elif etype == "customer.subscription.deleted":
        await _update(obj.get("metadata", {}).get("team_id", ""), {"status": "inactive"})

    elif etype == "invoice.payment_succeeded":
        try:
            sub      = stripe.Subscription.retrieve(obj.get("subscription", ""))
            meta     = sub.get("metadata", {})
            plan_key = meta.get("plan", "standard")
            await _update(meta.get("team_id", ""), {"status": "active", "subscription_plan": plan_key})
        except stripe.StripeError:
            pass

    elif etype == "invoice.payment_failed":
        try:
            sub = stripe.Subscription.retrieve(obj.get("subscription", ""))
            await _update(sub.get("metadata", {}).get("team_id", ""), {"status": "past_due"})
        except stripe.StripeError:
            pass

    return {"received": True}