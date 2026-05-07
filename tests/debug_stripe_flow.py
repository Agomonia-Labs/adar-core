"""
debug_stripe_flow.py — Diagnose and fix the Stripe checkout → activation flow.

Run: PYTHONPATH=$(pwd) python tests/debug_stripe_flow.py

Checks:
  1. All pending_payment teams in Firestore
  2. Their Stripe subscription status
  3. Fixes any teams that paid but weren't activated
  4. Tests the email system
  5. Shows what webhook secret is configured
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

SEP = "─" * 60


async def main():
    import stripe
    from google.cloud import firestore

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    frontend_url = os.environ.get("FRONTEND_URL", "")
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")

    print(SEP)
    print("ADAR — Stripe Flow Debugger")
    print(SEP)

    # ── 1. Config check ──────────────────────────────────────────────────────
    print("\n[1] Environment config")
    print(f"  STRIPE_SECRET_KEY:     {'✓ set' if stripe.api_key else '✗ MISSING'}")
    print(
        f"  STRIPE_WEBHOOK_SECRET: {'✓ ' + webhook_secret[:12] + '...' if webhook_secret else '✗ MISSING — webhook validation will fail'}")
    print(f"  FRONTEND_URL:          {frontend_url or '✗ MISSING — success_url will be wrong'}")
    print(f"  GMAIL_USER:            {gmail_user or '✗ MISSING — emails wont send'}")
    print(f"  GMAIL_APP_PASSWORD:    {'✓ set' if gmail_pass else '✗ MISSING'}")

    if not stripe.api_key:
        print("\n✗ STRIPE_SECRET_KEY not set — cannot continue")
        return

    # ── 2. Firestore — find stuck teams ─────────────────────────────────────
    print(f"\n{SEP}")
    print("[2] Firestore — checking adar_teams collection")
    db = firestore.AsyncClient(project="bdas-493785", database="tigers-arcl")

    all_teams = []
    async for doc in db.collection("adar_teams").stream():
        d = doc.to_dict()
        if d.get("team_id") == "admin":
            continue
        all_teams.append({"id": doc.id, **d})

    pending = [t for t in all_teams if t.get("status") == "pending_payment"]
    active = [t for t in all_teams if t.get("status") == "active"]

    print(f"  Total teams:           {len(all_teams)}")
    print(f"  Active:                {len(active)}")
    print(f"  Pending payment:       {len(pending)}")

    if pending:
        print(f"\n  ⚠ Stuck teams (pending_payment):")
        for t in pending:
            print(f"    • {t.get('team_name')} ({t.get('email')}) — doc_id={t['id']}")

    # ── 3. Check Stripe for each pending team ────────────────────────────────
    print(f"\n{SEP}")
    print("[3] Checking Stripe subscriptions for pending teams")

    fixed = []
    for team in pending:
        customer_id = team.get("stripe_customer_id")
        team_id = team["id"]
        team_name = team.get("team_name", team_id)

        if not customer_id:
            print(f"  ✗ {team_name}: no stripe_customer_id — cannot check Stripe")
            continue

        try:
            subs = stripe.Subscription.list(customer=customer_id, status="all", limit=5)
            found_active = None
            for sub in subs.get("data", []):
                status = sub.get("status")
                print(f"  → {team_name}: Stripe sub status = {status} (id={sub['id'][:20]}...)")
                if status in ("active", "trialing"):
                    found_active = sub

            if found_active:
                print(f"  ✓ {team_name} has active Stripe sub — fixing Firestore...")
                await db.collection("adar_teams").document(team_id).update({
                    "status": "active",
                    "subscription_status": found_active.get("status"),
                    "stripe_subscription_id": found_active.get("id"),
                    "approved_at": "auto-fixed by debug script",
                    "auto_approved": True,
                })
                fixed.append(team_name)
                print(f"  ✓ {team_name} activated!")
            else:
                print(f"  ✗ {team_name}: no active Stripe subscription found")
                print(f"    → Team may not have completed checkout")
                print(f"    → Force-activate anyway? (y/n): ", end="")
                ans = input().strip().lower()
                if ans == "y":
                    await db.collection("adar_teams").document(team_id).update({
                        "status": "active",
                        "approved_at": "force-fixed by debug script",
                    })
                    fixed.append(team_name)
                    print(f"  ✓ {team_name} force-activated!")

        except Exception as e:
            print(f"  ✗ {team_name}: Stripe error: {e}")

    # ── 4. Email test ────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("[4] Email system test")
    if not gmail_user or not gmail_pass:
        print("  ✗ Gmail not configured — skipping email test")
    else:
        print(f"  Sending test email to {gmail_user}...")
        try:
            from src.adar.notify import send_email
            await send_email(
                to=gmail_user,
                subject="Adar — debug email test",
                html=f"<p>Test email from debug_stripe_flow.py — Gmail SMTP is working ✓</p>"
            )
            print(f"  ✓ Test email sent to {gmail_user} — check your inbox")
        except Exception as e:
            print(f"  ✗ Email failed: {e}")

    # ── 5. Webhook config check ──────────────────────────────────────────────
    print(f"\n{SEP}")
    print("[5] Stripe webhook config")
    try:
        endpoints = stripe.WebhookEndpoint.list(limit=5)
        for ep in endpoints.get("data", []):
            print(f"  URL:    {ep.get('url')}")
            print(f"  Status: {ep.get('status')}")
            print(f"  Events: {', '.join(ep.get('enabled_events', []))[:80]}")
            print()
    except Exception as e:
        print(f"  Could not list webhook endpoints: {e}")

    print(f"  For local testing, run:")
    print(f"  stripe listen --forward-to localhost:8040/api/payments/webhook")
    print(f"  Then copy the whsec_xxx secret to your .env as STRIPE_WEBHOOK_SECRET")

    # ── 6. Summary ───────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("[6] Summary")
    if fixed:
        print(f"  ✓ Fixed {len(fixed)} team(s): {', '.join(fixed)}")
        print(f"  → Teams can now log in and use Adar")
        print(f"  → Welcome email will NOT be sent retroactively")
        print(f"    (send manually: python tests/debug_stripe_flow.py --send-welcome <email>)")
    else:
        print(f"  No teams fixed.")

    if pending and not fixed:
        print(f"\n  Next steps:")
        print(f"  1. Run: stripe listen --forward-to localhost:8040/api/payments/webhook")
        print(f"  2. Set STRIPE_WEBHOOK_SECRET in .env to the whsec_ value shown")
        print(f"  3. Restart backend: PYTHONPATH=$(pwd) python api/main.py")
        print(f"  4. Have team go through checkout again")

    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())