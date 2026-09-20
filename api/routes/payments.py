"""
api/routes/payments.py — Stripe payments for all domains.

Domain routing:
  DOMAIN=geetabitan → single plan: Adar Geetabitan Standard ($3.99/mo, 14-day trial)
  DOMAIN=arcl       → three plans: Basic / Standard / Unlimited
  DOMAIN=scheduling → ADAR Front Desk monthly ($50) and yearly ($450)

Both domains share the same endpoints. Plan config is resolved at runtime
from DOMAIN env var and the appropriate STRIPE_PRICE_* secret.
"""
from __future__ import annotations
import os, time
from datetime import datetime, timezone

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
    if DOMAIN == "scheduling":
        return {
            "monthly": {
                "name": "ADAR Front Desk Monthly",
                "price_id": os.getenv("STRIPE_PRICE_FRONT_DESK_MONTHLY", ""),
                "trial_days": 0,
                "quota": 500,
                "description": "$50/month",
                "amount": 5000,
                "currency": "usd",
                "interval": "month",
            },
            "yearly": {
                "name": "ADAR Front Desk Yearly",
                "price_id": os.getenv("STRIPE_PRICE_FRONT_DESK_YEARLY", ""),
                "trial_days": 0,
                "quota": 500,
                "description": "$450/year · Save $150",
                "amount": 45000,
                "currency": "usd",
                "interval": "year",
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


def _plan_key_from_subscription(subscription) -> str:
    catalogue = _plan_catalogue()
    try:
        items = subscription.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id", "") if items else ""
    except (AttributeError, IndexError, TypeError):
        price_id = ""
    for plan_key, plan in catalogue.items():
        if plan.get("price_id") and plan["price_id"] == price_id:
            return plan_key
    metadata = dict(subscription.get("metadata", {}) or {})
    return metadata.get("plan", next(iter(catalogue)))


def _stripe_dict(value) -> dict:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {}


def _validate_plan_price(plan_key: str, plan: dict) -> None:
    """Prevent a wrong Stripe secret from charging a different amount."""
    expected_amount = plan.get("amount")
    expected_interval = plan.get("interval")
    if expected_amount is None or not expected_interval:
        return
    try:
        price = stripe.Price.retrieve(plan["price_id"])
    except stripe.StripeError as exc:
        raise HTTPException(503, f"Stripe price for '{plan_key}' could not be loaded") from exc

    recurring_value = getattr(price, "recurring", None)
    if recurring_value is None and hasattr(price, "get"):
        recurring_value = price.get("recurring", {})
    recurring = _stripe_dict(recurring_value)
    currency = (getattr(price, "currency", None) or price.get("currency", "")).lower()
    amount = getattr(price, "unit_amount", None)
    if amount is None:
        amount = price.get("unit_amount")
    active = getattr(price, "active", None)
    if active is None:
        active = price.get("active", True)
    if currency != plan.get("currency", "usd") or amount != expected_amount \
            or recurring.get("interval") != expected_interval or not active:
        raise HTTPException(503, f"Stripe price for '{plan_key}' does not match the configured Front Desk plan")


def _frontend_url() -> str:
    if FRONTEND_URL:
        return FRONTEND_URL.rstrip("/")
    if DOMAIN == "geetabitan":
        return "https://geetabitan.adar.agomoniai.com"
    if DOMAIN == "restaurants":
        return "https://restaurants.adar.agomoniai.com"
    if DOMAIN == "scheduling":
        return "https://scheduling.adar.agomoniai.com"
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
    _validate_plan_price(plan_key, plan_cfg)

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
        subscription_data = {
            "metadata": {"team_id": team_id, "domain": DOMAIN, "plan": plan_key},
        }
        if int(plan_cfg.get("trial_days", 0)) > 0:
            subscription_data["trial_period_days"] = int(plan_cfg["trial_days"])
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": plan_cfg["price_id"], "quantity": 1}],
            mode="subscription",
            subscription_data=subscription_data,
            success_url=f"{base}?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
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
                "trial_days":  14,
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
                "trial_days":  14 if _billing_enabled() else 0,
            }],
        }
    if DOMAIN == "scheduling":
        return {
            "domain": "scheduling",
            "billing_enabled": _billing_enabled(),
            "plans": [
                {
                    "id": key,
                    "name": plan["name"],
                    "description": plan["description"],
                    "amount": plan["amount"],
                    "currency": plan["currency"].upper(),
                    "interval": plan["interval"],
                    "trial_days": plan["trial_days"],
                }
                for key, plan in _plan_catalogue().items()
            ],
        }
    # ARCL — single plan $12/month, 30-day trial
    return {
        "domain": "arcl",
        "plans": [
            {"id": "standard", "name": "Adar ARCL",
             "description": "$12/month · 30-day free trial · Full access",
             "amount": 1200, "currency": "USD", "interval": "month",
             "trial_days": 30},
        ],
    }


# ── Activate ──────────────────────────────────────────────────────────────────
@router.post("/activate")
async def activate(session_id: str = "", team: dict = Depends(get_current_team)):
    """Called after Stripe payment success. Updates team status to active and sends confirmation email."""
    import logging, time as _time
    logger    = logging.getLogger(__name__)
    team_id   = team.get("team_id", "")
    plan_key  = team.get("subscription_plan") or next(iter(_plan_catalogue()))

    if not team_id:
        raise HTTPException(400, "Missing team_id")
    if _billing_enabled() and not session_id:
        raise HTTPException(400, "A verified Stripe Checkout session is required")

    team_db = await _get_team_from_db(team_id)
    team_email = team_db.get("email") or team.get("email", "")
    team_name = team_db.get("team_name") or team.get("team_name", team_id)

    try:
        subscription_id = ""
        subscription_status = "active"
        customer_id = team_db.get("stripe_customer_id") or team.get("stripe_customer_id")
        if _billing_enabled():
            session = stripe.checkout.Session.retrieve(session_id)
            metadata = _stripe_dict(getattr(session, "metadata", None))
            if metadata.get("team_id") != team_id or metadata.get("domain") != DOMAIN:
                raise HTTPException(403, "Checkout session does not belong to this account")
            session_status = getattr(session, "status", None) or session.get("status")
            payment_status = getattr(session, "payment_status", None) or session.get("payment_status")
            if session_status != "complete" or payment_status not in {"paid", "no_payment_required"}:
                raise HTTPException(409, "Stripe Checkout has not completed")
            plan_key = metadata.get("plan", plan_key)
            subscription_id = getattr(session, "subscription", None) or session.get("subscription", "")
            customer_id = getattr(session, "customer", None) or session.get("customer", customer_id)
            if subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                subscription_status = (
                    getattr(subscription, "status", None)
                    or subscription.get("status", "")
                )
                if subscription_status not in {"active", "trialing"}:
                    raise HTTPException(409, "Stripe subscription is not active")
        # Get trial end date from Stripe
        trial_end_date = ""
        if customer_id and stripe.api_key:
            try:
                subs = stripe.Subscription.list(
                    customer=customer_id, status="all", limit=1
                )
                for sub in subs.auto_paging_iter():
                    if getattr(sub, "trial_end", None) and sub.trial_end > _time.time():
                        trial_end_date = datetime.utcfromtimestamp(
                            sub.trial_end
                        ).strftime("%B %d, %Y")
                    break
            except Exception as se:
                logger.warning(f"Could not fetch trial_end from Stripe: {se}")

        activated_at = datetime.now(timezone.utc).isoformat()
        await _update_team(team_id, {
            "status": "active",
            "subscription_status": subscription_status,
            "subscription_plan": plan_key,
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "subscription_activated_at": activated_at,
        })

        # Use the verified Checkout session as an idempotency key so a browser
        # refresh can never send a duplicate activation email.
        activation_email_sent = (
            team_db.get("subscription_activation_email_session_id") == session_id
        )
        email_sent = activation_email_sent
        if team_email and not activation_email_sent:
            try:
                from src.adar.notify import send_welcome_email
                email_sent = bool(await send_welcome_email(
                    to=team_email,
                    team_name=team_name,
                    plan=plan_key,
                    trial_ends=trial_end_date,
                ))
                if email_sent:
                    await _update_team(team_id, {
                        "welcome_email_sent": True,
                        "subscription_activation_email_session_id": session_id,
                        "subscription_activation_email_sent_at": datetime.now(timezone.utc).isoformat(),
                    })
                    logger.info(f"Subscription activation email sent to {team_email}")
            except Exception as mail_err:
                logger.warning(f"Welcome email failed (non-fatal): {mail_err}")

        return {"status": "activated", "plan": plan_key, "team_id": team_id,
                "trial_ends": trial_end_date, "email": team_email,
                "email_sent": email_sent}
    except HTTPException:
        raise
    except stripe.StripeError as e:
        raise HTTPException(502, f"Stripe activation error: {str(e)}")
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
        plan_key = _plan_key_from_subscription(obj)
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
            plan_key = _plan_key_from_subscription(sub)
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
