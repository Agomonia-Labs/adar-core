"""
payments.py — Stripe subscription integration.

Auto-payment flow:
  1. Team selects plan → POST /api/payments/create-checkout
  2. Redirected to Stripe hosted page → enters card once
  3. Stripe charges automatically every month/season
  4. Stripe webhook → updates Firestore on every event
  5. Failed payment → team notified, 7-day grace period, then suspended

Endpoints:
  POST /api/payments/create-checkout   create Stripe Checkout session
  GET  /api/payments/billing           current subscription + invoice history
  POST /api/payments/cancel            cancel at period end
  POST /api/payments/reactivate        undo cancellation
  POST /api/payments/webhook           Stripe webhook (no auth — verified by signature)
"""
import os
import json
import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google.cloud import firestore

from config import settings
from auth import get_current_team

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _s(obj):
    """Convert Stripe object to plain dict safely."""
    if obj is None:
        return {}
    try:
        return json.loads(str(obj))
    except Exception:
        return {}

TEAMS_COLLECTION = "adar_teams"

# Stripe config — set via Secret Manager in production
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# ── Stripe Price IDs — create these in Stripe Dashboard ──────────────────────
# Dashboard → Products → Add product → Add price → copy Price ID
PLANS = {
    "basic": {
        "name":        "Basic",
        "price_id":    os.environ.get("STRIPE_PRICE_BASIC",    "price_xxx"),  # $10/month
        "amount":      1000,  # cents — $10/month
        "currency":    "usd",
        "interval":    "month",
        "daily_quota": 50,
        "description": "50 messages/day · Player stats · Rules",
    },
    "standard": {
        "name":        "Standard",
        "price_id":    os.environ.get("STRIPE_PRICE_STANDARD", "price_xxx"),  # $15/month
        "amount":      1500,
        "currency":    "usd",
        "interval":    "month",
        "daily_quota": 200,
        "description": "200 messages/day · Full stats · Polls · Scorecards",
    },
    "unlimited": {
        "name":        "Unlimited",
        "price_id":    os.environ.get("STRIPE_PRICE_UNLIMITED", "price_xxx"),  # $30/month
        "amount":      3000,
        "currency":    "usd",
        "interval":    "month",
        "daily_quota": 1000,
        "description": "1000 messages/day · Everything · Priority support",
    },
}

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://arcl.tigers.agomoniai.com")


def get_db():
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


# ── Models ────────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str  # basic | standard | unlimited


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/plans")
async def list_plans():
    """Return available subscription plans — no auth required."""
    return {
        "plans": [
            {
                "id":          plan_id,
                "name":        plan["name"],
                "amount":      plan["amount"],
                "currency":    plan["currency"],
                "interval":    plan["interval"],
                "daily_quota": plan["daily_quota"],
                "description": plan["description"],
            }
            for plan_id, plan in PLANS.items()
        ]
    }


@router.post("/create-checkout")
async def create_checkout(
    req: CheckoutRequest,
    team: dict = Depends(get_current_team),
):
    """
    Create a Stripe Checkout session for subscription.
    Returns a URL to redirect the team to Stripe's hosted payment page.
    Team enters card once — Stripe auto-charges every billing period.
    """
    if req.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {req.plan}")

    team_id = team.get("team_id")
    if not team_id or team_id == "admin":
        raise HTTPException(
            status_code=400,
            detail="Admin accounts cannot subscribe. Log in as a team account."
        )

    plan = PLANS[req.plan]
    db = get_db()

    try:
        # Get or create Stripe customer
        doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
        team_data = doc.to_dict() if doc.exists else {}
        logger.info(f"Team data: {team_id} exists={doc.exists}")

        stripe_customer_id = team_data.get("stripe_customer_id")

        if not stripe_customer_id:
            customer = stripe.Customer.create(
                email=team_data.get("email", ""),
                name=team_data.get("team_name", team_id),
                metadata={"team_id": team_id},
            )
            stripe_customer_id = customer.id
            await db.collection(TEAMS_COLLECTION).document(team_id).update({
                "stripe_customer_id": stripe_customer_id,
            })
            logger.info(f"Created Stripe customer: {stripe_customer_id}")

        price_id = plan["price_id"]
        logger.info(f"Using price_id: {price_id}")

        # Set invoice custom fields on the customer (persists on all invoices)
        _s(stripe.Customer.modify(
            stripe_customer_id,
            invoice_settings={
                "custom_fields": [
                    {"name": "Team",   "value": team_data.get("team_name", team_id)[:30]},
                    {"name": "Plan",   "value": req.plan.capitalize()},
                    {"name": "League", "value": "ARCL"},
                ],
                "footer": "Thank you for supporting ARCL cricket.",
            },
        ))

        if not price_id or price_id == "price_xxx":
            raise ValueError(
                f"STRIPE_PRICE_{req.plan.upper()} env var not set. "
                f"Add it to .env with the Price ID from Stripe Dashboard."
            )

        # Create Checkout session
        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={
                "trial_period_days": 14,
                "metadata": {"team_id": team_id, "plan": req.plan},
            },
            metadata={"team_id": team_id, "plan": req.plan},
            success_url=f"{FRONTEND_URL}?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}?payment=cancelled",
            allow_promotion_codes=True,
        )

        session_d = _s(session)
        url = session_d.get("url", "")
        logger.info(f"Checkout session created: team={team_id} plan={req.plan} url={url[:40]}...")
        return {"checkout_url": url, "session_id": session_d.get("id")}

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error in create-checkout: {e}")
        raise HTTPException(status_code=400, detail=f"Stripe error: {e.user_message or str(e)}")
    except ValueError as e:
        logger.error(f"Config error in create-checkout: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in create-checkout: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Checkout failed: {e}")


@router.get("/billing")
async def get_billing(team: dict = Depends(get_current_team)):
    """
    Return current subscription status and recent invoices.
    """
    team_id = team["team_id"]
    db = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")

    d = doc.to_dict()
    sub_id = d.get("stripe_subscription_id")

    billing = {
        "team_id":             team_id,
        "subscription_status": d.get("subscription_status", "none"),
        "subscription_plan":   d.get("subscription_plan", "none"),
        "subscription_ends_at":d.get("subscription_ends_at"),
        "trial_ends_at":       d.get("trial_ends_at"),
        "daily_quota":         d.get("daily_quota", 0),
        "usage_today":         d.get("usage_today", 0),
        "cancel_at_period_end":d.get("cancel_at_period_end", False),
        "invoices":            [],
    }

    # Fetch invoices from Stripe
    if sub_id and stripe.api_key:
        try:
            invoices_obj = stripe.Invoice.list(subscription=sub_id, limit=10)
            invoices_d   = _s(invoices_obj)
            billing["invoices"] = [
                {
                    "id":      inv.get("id"),
                    "amount":  (inv.get("amount_paid") or 0) / 100,
                    "currency": (inv.get("currency") or "usd").upper(),
                    "status":   inv.get("status"),
                    "date":     datetime.fromtimestamp(inv["created"], tz=timezone.utc).strftime("%Y-%m-%d") if inv.get("created") else "",
                    "pdf_url":  inv.get("invoice_pdf"),
                }
                for inv in invoices_d.get("data", [])
            ]
        except Exception as e:
            logger.warning(f"Could not fetch invoices: {e}")

    return billing


@router.post("/cancel")
async def cancel_subscription(team: dict = Depends(get_current_team)):
    """
    Cancel subscription at end of current billing period.
    Team retains access until period ends — no immediate cutoff.
    """
    team_id = team["team_id"]
    db = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    d = doc.to_dict() if doc.exists else {}
    sub_id = d.get("stripe_subscription_id")

    if not sub_id:
        raise HTTPException(status_code=400, detail="No active subscription found")

    # cancel_at_period_end=True means access continues until period ends
    _s(stripe.Subscription.modify(sub_id, cancel_at_period_end=True))

    await db.collection(TEAMS_COLLECTION).document(team_id).update({
        "cancel_at_period_end": True,
    })

    ends_at = d.get("subscription_ends_at", "end of billing period")
    return {
        "message": f"Subscription will cancel at {ends_at}. You keep full access until then.",
        "cancel_at_period_end": True,
    }


@router.post("/reactivate")
async def reactivate_subscription(team: dict = Depends(get_current_team)):
    """Undo a cancellation — team stays subscribed."""
    team_id = team["team_id"]
    db = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    d = doc.to_dict() if doc.exists else {}
    sub_id = d.get("stripe_subscription_id")

    if not sub_id:
        raise HTTPException(status_code=400, detail="No subscription found")

    _s(stripe.Subscription.modify(sub_id, cancel_at_period_end=False))

    await db.collection(TEAMS_COLLECTION).document(team_id).update({
        "cancel_at_period_end": False,
    })

    return {"message": "Subscription reactivated — you will continue to be billed."}


@router.post("/portal")
async def create_portal(team: dict = Depends(get_current_team)):
    """
    Create a Stripe Customer Portal session.
    Teams can update card, view invoices, change plan — all hosted by Stripe.
    """
    team_id = team["team_id"]
    db = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    d = doc.to_dict() if doc.exists else {}
    customer_id = d.get("stripe_customer_id")

    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found")

    session = _s(stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{FRONTEND_URL}?billing=returned",
    ))
    return {"portal_url": session.get("url")}


# ── Stripe Webhook ────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook — called by Stripe on every subscription event.
    No JWT auth — verified by Stripe signature instead.
    Register this URL in Stripe Dashboard → Webhooks.
    """
    payload   = await request.body()
    sig       = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    db = get_db()
    event_type = event["type"]
    logger.info(f"Stripe webhook: {event_type}")

    # ── Checkout completed — subscription created ─────────────────────────────
    if event_type == "checkout.session.completed":
        try:
            session = _s(event["data"]["object"])
            team_id = (session.get("metadata") or {}).get("team_id")
            plan    = (session.get("metadata") or {}).get("plan", "standard")
            sub_id  = session.get("subscription")

            logger.info(f"Checkout completed: team={team_id} plan={plan} sub_id={sub_id}")

            if not team_id:
                logger.warning("checkout.session.completed: no team_id in metadata")
                return {"received": True}

            plan_d = PLANS.get(plan, PLANS["standard"])
            update_data = {
                "subscription_plan":    plan,
                "daily_quota":          plan_d["daily_quota"],
                "cancel_at_period_end": False,
            }

            if sub_id:
                try:
                    sub = stripe.Subscription.retrieve(sub_id)
                    status     = sub.status  # trialing, active, etc.
                    trial_end  = datetime.fromtimestamp(sub.trial_end, tz=timezone.utc).isoformat()                                  if sub.trial_end else None
                    period_end = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc).isoformat()                                  if sub.get("current_period_end") else None
                    update_data.update({
                        "stripe_subscription_id": sub_id,
                        "subscription_status":    status,
                        "subscription_ends_at":   period_end,
                        "trial_ends_at":          trial_end,
                    })
                except Exception as e:
                    logger.warning(f"Could not retrieve subscription {sub_id}: {e}")
                    update_data["subscription_status"] = "active"
            else:
                # One-time payment (no subscription)
                update_data["subscription_status"] = "active"

            await db.collection(TEAMS_COLLECTION).document(team_id).set(update_data, merge=True)
            logger.info(f"Subscription created: team={team_id} plan={plan} status={update_data.get('subscription_status')}")

        except Exception as e:
            logger.error(f"Error handling checkout.session.completed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # ── Subscription renewed successfully ─────────────────────────────────────
    elif event_type == "invoice.payment_succeeded":
        invoice = _s(event["data"]["object"])
        sub_id  = invoice.get("subscription")
        if not sub_id:
            logger.debug("invoice.payment_succeeded: manual invoice, no subscription")
        else:
            try:
                sub     = _s(stripe.Subscription.retrieve(sub_id))
                meta    = sub.get("metadata") or {}
                team_id = meta.get("team_id")
                if team_id:
                    period_end = datetime.fromtimestamp(
                        sub["current_period_end"], tz=timezone.utc
                    ).isoformat() if sub.get("current_period_end") else None
                    await db.collection(TEAMS_COLLECTION).document(team_id).set({
                        "subscription_status":  "active",
                        "subscription_ends_at": period_end,
                        "usage_today":          0,
                    }, merge=True)
                    logger.info(f"Subscription renewed: team={team_id}")
            except Exception as e:
                logger.error(f"invoice.payment_succeeded error: {e}")

    # ── Payment failed — grace period ─────────────────────────────────────────
    elif event_type == "invoice.payment_failed":
        invoice = _s(event["data"]["object"])
        sub_id  = invoice.get("subscription")
        if sub_id:
            sub     = stripe.Subscription.retrieve(sub_id)
            team_id = sub["metadata"].get("team_id")
            if team_id:
                attempt = invoice.get("attempt_count", 1)
                # Stripe retries 3 times over 7 days — keep active during retries
                # Only suspend after all retries exhausted (handled by subscription.deleted)
                await db.collection(TEAMS_COLLECTION).document(team_id).set({
                    "subscription_status": "past_due",
                }, merge=True)
                logger.warning(f"Payment failed: team={team_id} attempt={attempt}")

    # ── Subscription cancelled or deleted ─────────────────────────────────────
    elif event_type == "customer.subscription.deleted":
        sub     = _s(event["data"]["object"])
        meta    = sub.get("metadata") or {}
        team_id = meta.get("team_id")
        if team_id:
            await db.collection(TEAMS_COLLECTION).document(team_id).set({
                "subscription_status": "canceled",
                "daily_quota":         0,
            }, merge=True)
            logger.info(f"Subscription cancelled: team={team_id}")

    # ── Trial ending soon (3 days before) ────────────────────────────────────
    elif event_type == "customer.subscription.trial_will_end":
        sub     = _s(event["data"]["object"])
        meta    = sub.get("metadata") or {}
        team_id = meta.get("team_id")
        trial_end = datetime.fromtimestamp(sub["trial_end"], tz=timezone.utc).strftime("%Y-%m-%d") if sub.get("trial_end") else "soon"
        if team_id:
            logger.info(f"Trial ending soon: team={team_id} ends={trial_end}")

    # ── Subscription status changed (upgrade/downgrade) ───────────────────────
    elif event_type == "customer.subscription.updated":
        sub     = event["data"]["object"]
        team_id = sub["metadata"].get("team_id")
        if team_id:
            plan_name = sub["metadata"].get("plan", "standard")
            plan_d    = PLANS.get(plan_name, PLANS["standard"])
            period_end = datetime.fromtimestamp(
                sub["current_period_end"]
            ).isoformat() if sub.get("current_period_end") else None
            await db.collection(TEAMS_COLLECTION).document(team_id).update({
                "subscription_status":    sub["status"],
                "subscription_ends_at":   period_end,
                "cancel_at_period_end":   sub.get("cancel_at_period_end", False),
                "daily_quota":            plan_d["daily_quota"],
            })

    # Log unhandled events but always return 200
    # so Stripe doesn't retry them
    if not event_type.startswith(("checkout.", "invoice.payment", "customer.subscription.")):
        logger.debug(f"Unhandled Stripe event: {event_type}")

    return {"received": True}