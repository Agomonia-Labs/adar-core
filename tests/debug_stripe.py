"""
debug_stripe.py — Check Stripe subscription and sync to Firestore.
Run: python debug_stripe.py
"""
import asyncio, os, sys, json
from datetime import datetime, timezone

sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

import stripe
from google.cloud import firestore

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
GCP_PROJECT    = os.environ.get("GCP_PROJECT_ID", "")
FIRESTORE_DB   = os.environ.get("FIRESTORE_DATABASE", "(default)")
TEAM_ID        = "agomoni_tigers"
PLANS          = {"basic": 50, "standard": 200, "unlimited": 1000}

def to_dict(obj):
    """Convert any Stripe object to a plain Python dict."""
    return json.loads(str(obj))

def ts(val):
    try:
        return datetime.fromtimestamp(int(val), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "none"

async def main():
    db = firestore.AsyncClient(project=GCP_PROJECT, database=FIRESTORE_DB)

    print("=" * 60)
    print("STEP 1 — Firestore")
    print("=" * 60)
    doc = await db.collection("adar_teams").document(TEAM_ID).get()
    d = doc.to_dict() if doc.exists else {}
    customer_id = d.get("stripe_customer_id")
    print(f"  stripe_customer_id:  {customer_id}")
    print(f"  subscription_status: {d.get('subscription_status')}")
    print(f"  subscription_plan:   {d.get('subscription_plan')}")
    print(f"  daily_quota:         {d.get('daily_quota')}")
    print()

    if not stripe.api_key:
        print("ERROR: STRIPE_SECRET_KEY not set"); return

    mode = "LIVE" if stripe.api_key.startswith("sk_live") else "TEST"
    print(f"  Stripe mode: {mode}\n")

    if not customer_id:
        print("No stripe_customer_id. Complete checkout first."); return

    print("=" * 60)
    print("STEP 2 — Stripe customer")
    print("=" * 60)
    try:
        customer = stripe.Customer.retrieve(customer_id)
        cd = to_dict(customer)
        print(f"  Customer: {customer_id}  OK")
        print(f"  Email:    {cd.get('email','n/a')}")
        print()
    except Exception as e:
        print(f"  ERROR: {e}")
        if "No such customer" in str(e):
            ans = input("  Clear stripe_customer_id from Firestore? (y/n): ").strip().lower()
            if ans == "y":
                await db.collection("adar_teams").document(TEAM_ID).update({
                    "stripe_customer_id":     None,
                    "stripe_subscription_id": None,
                    "subscription_status":    None,
                })
                print("  Cleared. Run checkout again.")
        return

    print("=" * 60)
    print("STEP 3 — Subscriptions")
    print("=" * 60)
    resp = stripe.Subscription.list(customer=customer_id, limit=5)
    resp_d = to_dict(resp)
    subs = resp_d.get("data", [])

    if not subs:
        print("  No subscriptions found in Stripe.")
        return

    for sub in subs:
        meta       = sub.get("metadata") or {}
        plan_meta  = meta.get("plan", "unknown")
        team_meta  = meta.get("team_id", "NOT SET")
        status     = sub.get("status", "unknown")
        trial_end  = ts(sub["trial_end"]) if sub.get("trial_end") else "none"
        period_end = ts(sub["current_period_end"]) if sub.get("current_period_end") else "none"
        sub_id     = sub.get("id", "")
        cancel_end = sub.get("cancel_at_period_end", False)

        print(f"  ID:          {sub_id}")
        print(f"  Status:      {status}")
        print(f"  Plan:        {plan_meta}")
        print(f"  team_id:     {team_meta}")
        print(f"  Trial ends:  {trial_end}")
        print(f"  Period ends: {period_end}")
        print()

        ans = input(f"  Sync to Firestore for '{TEAM_ID}'? (y/n): ").strip().lower()
        if ans == "y":
            quota = PLANS.get(plan_meta, 200)
            await db.collection("adar_teams").document(TEAM_ID).set({
                "stripe_subscription_id": sub_id,
                "subscription_status":    status,
                "subscription_plan":      plan_meta,
                "subscription_ends_at":   period_end,
                "trial_ends_at":          trial_end if trial_end != "none" else None,
                "daily_quota":            quota,
                "cancel_at_period_end":   cancel_end,
            }, merge=True)
            print(f"  ✓ Synced: status={status} plan={plan_meta} quota={quota}/day")
            break

    print()
    print("=" * 60)
    print("STEP 4 — Final Firestore state")
    print("=" * 60)
    doc2 = await db.collection("adar_teams").document(TEAM_ID).get()
    d2 = doc2.to_dict() if doc2.exists else {}
    print(f"  subscription_status: {d2.get('subscription_status')}")
    print(f"  subscription_plan:   {d2.get('subscription_plan')}")
    print(f"  daily_quota:         {d2.get('daily_quota')}")
    print(f"  trial_ends:          {str(d2.get('trial_ends_at',''))[:10]}")
    print(f"  period_ends:         {str(d2.get('subscription_ends_at',''))[:10]}")
    print("\nDone.")

asyncio.run(main())