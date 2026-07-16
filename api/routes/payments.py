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
from src.adar.db import get_db

router = APIRouter(prefix="/api/payments", tags=["payments"])

# ── Stripe globals ─────────────────────────────────────────────────────────────
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
DOMAIN           = os.getenv("DOMAIN", "arcl")
TEAMS_COLLECTION = "adar_teams"   # must match auth.py
FRONTEND_URL   = os.getenv("FRONTEND_URL", "")


def _billing_enabled() -> bool:
    return os.getenv("BILLING_ENABLED", "true").lower() == "true"


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
    if DOMAIN == "restaurants":
        return {
            "standard": {
                "name":        "Adar Restaurants Standard",
                "price_id":    os.getenv("STRIPE_PRICE_RESTAURANTS", ""),
                "trial_days":  14,
                "quota":       500,
                "description": "Restaurant recommendations, menu search, price comparison",
            },
        }
    return {
        "basic": {
            "name":        "Adar ARCL",
            "price_id":    os.getenv("STRIPE_PRICE_STANDARD", ""),
            "trial_days":  30,
            "quota":       1000,
            "description": "$12/month · 30-day free trial · Full access",
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
    if DOMAIN == "geetabitan":
        return "https://geetabitan.adar.agomoniai.com"
    if DOMAIN == "restaurants":
        return "https://restaurants.adar.agomoniai.com"
    return "https://arcl.agomoniai.com"


def _fs_update(team_id: str, updates: dict):
    """Sync Firestore upsert — creates document if it doesn't exist."""
    from google.cloud import firestore
    db  = firestore.Client(database=os.getenv("FIRESTORE_DATABASE", "tigers-arcl"))
    ref = db.collection(TEAMS_COLLECTION).document(team_id)
    # set(merge=True) creates the doc if missing, updates fields if it exists
    ref.set(updates, merge=True)


async def _get_team_from_db(team_id: str) -> dict:
    """Fetch fresh team data from Firestore — JWT doesn't contain stripe_customer_id."""
    db = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    return doc.to_dict() or {} if doc.exists else {}


async def _get_team_from_db(team_id: str) -> dict:
    """Fetch fresh team data from Firestore — JWT doesn't contain stripe_customer_id."""
    db = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    return doc.to_dict() or {} if doc.exists else {}


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
    if not _billing_enabled():
        team_id = team["team_id"]
        plan_cfg, plan_key = _get_plan(req.plan)
        await _update_team(team_id, {
            "status": "active",
            "subscription_status": "active",
            "subscription_plan": plan_key,
            "daily_quota": plan_cfg.get("quota", 500),
        })
        success_url = f"{_frontend_url()}?payment=success"
        return {"url": success_url, "checkout_url": success_url, "billing_disabled": True}

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
    if not _billing_enabled():
        raise HTTPException(400, "Billing is disabled for this environment")
    # Fetch from Firestore — stripe_customer_id is not in JWT
    team_id = team.get("team_id", "")
    team_db = await _get_team_from_db(team_id)
    customer_id = team_db.get("stripe_customer_id") or team.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found")
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=_frontend_url())
    return {"url": session.url, "portal_url": session.url}


# ── Billing info ──────────────────────────────────────────────────────────────
@router.get("/billing")
async def get_billing(team: dict = Depends(get_current_team)):
    catalogue   = _plan_catalogue()
    if not _billing_enabled():
        plan_key = team.get("subscription_plan", "standard")
        return {
            "status": "active",
            "domain": DOMAIN,
            "plan": plan_key,
            "plan_name": catalogue.get(plan_key, {}).get("name", plan_key),
            "subscription_status": "active",
            "subscription_plan": plan_key,
            "trial_days_remaining": None,
            "next_billing_date": None,
            "cancel_at_period_end": False,
            "invoices": [],
            "usage_today": 0,
            "daily_quota": catalogue.get(plan_key, {}).get("quota", 500),
            "billing_disabled": True,
        }
    # Fetch fresh from Firestore — stripe_customer_id is not in JWT
    team_id  = team.get("team_id", "")
    team_db  = await _get_team_from_db(team_id)
    customer_id = team_db.get("stripe_customer_id") or team.get("stripe_customer_id")
    if not customer_id:
        return {"status": "inactive", "domain": DOMAIN,
                "message": "No billing account found. Please subscribe first."}
    try:
        import logging as _log
        _log.info(f"[billing] Fetching Stripe subs for customer={customer_id}")
        subs = stripe.Subscription.list(customer=customer_id, status="all", limit=1)
        _log.info(f"[billing] Found {len(subs.data)} subscriptions")
        if not subs.data:
            return {"status": "inactive", "domain": DOMAIN}
        sub      = subs.data[0]
        # Stripe SDK returns objects — use attribute access with fallbacks
        # Use Firestore subscription_plan — more reliable than Stripe metadata
        plan_key = team_db.get("subscription_plan", "standard") or "standard"
        trial_end = getattr(sub, "trial_end", None)
        trial_days = max(0, int((trial_end - time.time()) / 86400)) if trial_end and trial_end > time.time() else None
        period_end = getattr(sub, "current_period_end", None)
        next_date  = datetime.utcfromtimestamp(period_end).isoformat() if period_end else None
        # Fetch invoices
        invoices = []
        try:
            inv_list = stripe.Invoice.list(customer=customer_id, limit=10)
            for inv in inv_list.data:
                amount_paid = getattr(inv, "amount_paid", 0) or 0
                amount_due  = getattr(inv, "amount_due",  0) or 0
                if amount_paid > 0 or amount_due > 0:
                    invoices.append({
                        "id":       getattr(inv, "id", ""),
                        "date":     datetime.utcfromtimestamp(getattr(inv, "created", 0)).strftime("%b %d, %Y"),
                        "amount":   (amount_paid or amount_due) / 100,
                        "currency": (getattr(inv, "currency", "usd") or "usd").upper(),
                        "status":   getattr(inv, "status", ""),
                        "pdf_url":  getattr(inv, "invoice_pdf", "") or "",
                    })
        except Exception:
            pass

        trial_end_date = None
        if trial_end and trial_end > time.time():
            try:
                trial_end_date = datetime.utcfromtimestamp(trial_end).strftime("%Y-%m-%d")
            except Exception:
                trial_end_date = None

        return {
            # New field names
            "status":               getattr(sub, "status", "unknown"),
            "domain":               DOMAIN,
            "plan":                 plan_key,
            "plan_name":            catalogue.get(plan_key, {}).get("name", plan_key),
            "trial_days_remaining": trial_days,
            "next_billing_date":    next_date,
            "cancel_at_period_end": getattr(sub, "cancel_at_period_end", False),
            # Legacy field names (Billing.jsx compatibility)
            "subscription_status":  getattr(sub, "status", "unknown"),
            "subscription_plan":    plan_key,
            "trial_end_date":       trial_end_date,
            "trial_ends_at":        trial_end_date,
            "subscription_ends_at": next_date,
            "invoices":             invoices,
            "usage_today":          0,   # populated by caller if needed
            "daily_quota":          catalogue.get(plan_key, {}).get("quota", 200),
        }
    except stripe.StripeError as e:
        import logging as _log
        _log.error(f"[billing] Stripe error: {e}")
        raise HTTPException(500, str(e))
    except Exception as e:
        import logging as _log
        _log.error(f"[billing] Unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Billing error: {str(e)}")


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
    if DOMAIN == "restaurants":
        return {
            "domain": "restaurants",
            "billing_enabled": _billing_enabled(),
            "plans": [{
                "id":          "standard",
                "name":        "Adar Restaurants Standard",
                "description": "Restaurant recommendations, menu search, price comparison",
                "amount":      0 if not _billing_enabled() else 999,
                "currency":    "USD",
                "interval":    "month",
            }],
        }
    # ARCL — single plan $12/month, 30-day trial
    return {
        "domain": "arcl",
        "plans": [
            {"id": "standard", "name": "Adar ARCL",
             "description": "$12/month · 30-day free trial · Full access",
             "amount": 1200, "currency": "USD", "interval": "month"},
        ],
    }


# ── Activate ──────────────────────────────────────────────────────────────────
@router.post("/activate")
async def activate(team: dict = Depends(get_current_team)):
    """Called after Stripe payment success. Updates team status to active and sends confirmation email."""
    import logging, time as _time
    logger    = logging.getLogger(__name__)
    team_id   = team.get("team_id", "")
    plan_key  = team.get("subscription_plan", "standard")
    team_email = team.get("email", "")
    team_name  = team.get("team_name", team_id)

    if not team_id:
        raise HTTPException(400, "Missing team_id")

    try:
        # Get trial end date from Stripe
        trial_end_date = ""
        customer_id = team.get("stripe_customer_id")
        if customer_id and stripe.api_key:
            try:
                subs = stripe.Subscription.list(
                    customer=customer_id, status="all", limit=1
                )
                for sub in subs.auto_paging_iter():
                    if getattr(sub, "trial_end", None) and sub.trial_end > _time.time():
                        from datetime import datetime
                        trial_end_date = datetime.utcfromtimestamp(
                            sub.trial_end
                        ).strftime("%B %d, %Y")
                    break
            except Exception as se:
                logger.warning(f"Could not fetch trial_end from Stripe: {se}")

        await _update_team(team_id, {
            "status":            "active",
            "subscription_plan": plan_key,
        })

        # Send confirmation email if not already sent
        if team_email and not team.get("welcome_email_sent"):
            try:
                from src.adar.notify import send_welcome_email
                await send_welcome_email(
                    to=team_email,
                    team_name=team_name,
                    plan=plan_key,
                    trial_ends=trial_end_date,
                )
                await _update_team(team_id, {"welcome_email_sent": True})
                logger.info(f"Welcome email sent to {team_email} (trial ends {trial_end_date})")
            except Exception as mail_err:
                logger.warning(f"Welcome email failed (non-fatal): {mail_err}")

        return {"status": "activated", "plan": plan_key, "team_id": team_id,
                "trial_ends": trial_end_date}
    except Exception as e:
        raise HTTPException(500, f"Activation error: {str(e)}")


# ── Stripe webhook (handles both domains) ────────────────────────────────────
@router.post("/cancel")
async def cancel_subscription(
    team: dict = Depends(get_current_team),
):
    """Cancel at period end."""
    import logging
    team_id = team.get("team_id", "")
    team_db = await _get_team_from_db(team_id)
    customer_id = team_db.get("stripe_customer_id") or team.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found — please contact support")
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            subs = stripe.Subscription.list(customer=customer_id, status="trialing", limit=1)
        if not subs.data:
            raise HTTPException(404, "No active subscription found")
        stripe.Subscription.modify(subs.data[0].id, cancel_at_period_end=True)
        _period_end = getattr(subs.data[0], "current_period_end", None)
        _ends_at = datetime.utcfromtimestamp(_period_end).strftime("%B %d, %Y") if _period_end else ""
        logging.info(f"Subscription cancelled for team={team_id} ends_at={_ends_at}")
        if team_db.get("email"):
            from src.adar.notify import send_subscription_cancelled_email
            try:
                await send_subscription_cancelled_email(
                    to=team_db["email"],
                    team_name=team_db.get("team_name", team_id),
                    ends_at=_ends_at,
                )
                logging.info(f"Cancel email sent to {team_db['email']}")
            except Exception as _em:
                logging.error(f"Cancel email failed: {_em}")
        return {"message": "Subscription will cancel at end of billing period."}
    except stripe.StripeError as e:
        raise HTTPException(500, str(e))


@router.post("/reactivate")
async def reactivate_subscription(
    team: dict = Depends(get_current_team),
):
    """Undo cancel_at_period_end."""
    import logging
    team_id = team.get("team_id", "")
    team_db = await _get_team_from_db(team_id)
    customer_id = team_db.get("stripe_customer_id") or team.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found — please contact support")
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            subs = stripe.Subscription.list(customer=customer_id, status="trialing", limit=1)
        if not subs.data:
            raise HTTPException(404, "No active subscription found")
        stripe.Subscription.modify(subs.data[0].id, cancel_at_period_end=False)
        _period_end = getattr(subs.data[0], "current_period_end", None)
        _next_billing = datetime.utcfromtimestamp(_period_end).strftime("%B %d, %Y") if _period_end else ""
        logging.info(f"Subscription reactivated for team={team_id}")
        if team_db.get("email"):
            from src.adar.notify import send_reactivation_email
            try:
                await send_reactivation_email(
                    to=team_db["email"],
                    team_name=team_db.get("team_name", team_id),
                    next_billing=_next_billing,
                )
                logging.info(f"Reactivation email sent to {team_db['email']}")
            except Exception as _em:
                logging.error(f"Reactivation email failed: {_em}")
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
            meta     = dict(getattr(sub, "metadata", None) or {})
            plan_key = meta.get("plan", "standard")
            await _update(meta.get("team_id", ""), {"status": "active", "subscription_plan": plan_key})
        except stripe.StripeError:
            pass

    elif etype == "invoice.payment_failed":
        try:
            sub = stripe.Subscription.retrieve(obj.get("subscription", ""))
            await _update(dict(getattr(sub, "metadata", None) or {}).get("team_id", ""), {"status": "past_due"})
        except stripe.StripeError:
            pass

    return {"received": True}