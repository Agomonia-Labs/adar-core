"""
notify.py — Gmail SMTP email notifications for Adar ARCL.

Sends emails for:
- Trial started (welcome)
- Trial ending in 3 days (reminder)
- Payment succeeded (receipt)
- Payment failed (urgent action)
- Subscription cancelled (confirmation)

Setup:
  1. Generate Gmail App Password: myaccount.google.com → Security → App Passwords
  2. Get API key: Dashboard → Settings → API Keys → Create API Key
  3. Verify sender email: Settings → Sender Authentication
  2. Add to GCP Secrets: gmail-user, gmail-app-password, from-email, frontend-url
  5. Add to .env: NOTIFY_FROM_EMAIL=noreply@adar.agomoniai.com
"""
import os
import logging
from datetime import datetime

from src.adar.config import DOMAIN

logger = logging.getLogger(__name__)

# Every domain shares this module (Gmail sending, OTP login codes, the base
# HTML template) — brand text needs to follow DOMAIN, not stay hardcoded to
# ARCL. FROM_NAME feeds the email's actual "From:" header display name, and
# _BRAND feeds _base_template's default brand_name/footer_org below, so a
# call site that doesn't explicitly override branding (send_otp_email, for
# instance) still shows correctly per domain instead of always saying
# "Adar ARCL". Billing-flow emails (welcome/trial/payment/etc. further down)
# stay ARCL-worded on purpose — Stripe billing isn't wired up for any other
# domain yet (BILLING_ENABLED=false), so they're unreachable elsewhere.
_BRAND_DEFAULTS = {
    "arcl":        {"brand_name": "Adar ARCL",       "footer_org": "American Recreational Cricket League"},
    "geetabitan":  {"brand_name": "Adar Geetabitan",  "footer_org": "গীতবিতান — রবীন্দ্রনাথ ঠাকুরের গান"},
    "restaurants": {"brand_name": "Adar Restaurants", "footer_org": "Restaurant Food Recommender"},
    "scheduling":  {"brand_name": "Adar Scheduling",  "footer_org": "Practice Scheduling Assistant"},
}
_BRAND = _BRAND_DEFAULTS.get(DOMAIN, _BRAND_DEFAULTS["arcl"])

FROM_EMAIL     = os.environ.get("NOTIFY_FROM_EMAIL", "noreply@adar.agomoniai.com")
FROM_NAME      = _BRAND["brand_name"]
APP_URL        = os.environ.get("FRONTEND_URL", "https://adar.agomoniai.com")
GMAIL_USER     = os.environ.get("GMAIL_USER", "admin@agomoniai.com")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")


async def send_email(to: str, subject: str, html: str):
    import logging as _log
    _log.info(f"[notify] Sending email to={to} subject={subject[:40]}")
    """Send email via Gmail SMTP."""
    if not to or "@" not in to:
        logger.warning(f"Invalid email address: {to}")
        return

    if GMAIL_USER and GMAIL_APP_PASS:
        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{FROM_NAME} <{GMAIL_USER}>"
            msg["To"]      = to
            msg.attach(MIMEText(html, "html"))
            import ssl, certifi
            # Use certifi certs on Mac; on Linux (Cloud Run) system certs work fine
            try:
                tls_context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                tls_context = ssl.create_default_context()
            await aiosmtplib.send(
                msg,
                hostname="smtp.gmail.com",
                port=587,
                username=GMAIL_USER,
                password=GMAIL_APP_PASS,
                start_tls=True,
                tls_context=tls_context,
            )
            logger.info(f"Email sent via Gmail: to={to} subject='{subject}'")
            return
        except Exception as e:
            logger.error(f"Gmail SMTP error: {e}")

    # No email provider configured — just log
    logger.warning(f"No email provider configured. Would have sent to={to} subject='{subject}'")


def _base_template(
    title: str,
    body: str,
    logo_text: str = "আদর",
    brand_name: str = _BRAND["brand_name"],
    footer_org: str = _BRAND["footer_org"],
) -> str:
    """Simple branded HTML email template. Defaults follow the running
    domain (see _BRAND above) so a call site only needs to pass
    logo_text/brand_name/footer_org when it wants to override that."""
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body style="font-family: 'Inter', Arial, sans-serif; background: #F5FBF7; margin: 0; padding: 32px 16px;">
  <div style="max-width: 520px; margin: 0 auto; background: #fff; border-radius: 12px;
              border: 1px solid #C8E8D8; overflow: hidden;">

    <!-- Header -->
    <div style="background: #2EB87E; padding: 24px 32px; display: flex; align-items: center;">
      <span style="font-size: 1.4rem; font-weight: 700; color: #fff; margin-right: 10px;">{logo_text}</span>
      <span style="font-size: 1.1rem; font-weight: 600; color: #fff;">{brand_name}</span>
    </div>

    <!-- Body -->
    <div style="padding: 32px; color: #1A3326; line-height: 1.6;">
      {body}
    </div>

    <!-- Footer -->
    <div style="padding: 20px 32px; background: #F5FBF7; border-top: 1px solid #C8E8D8;
                font-size: 0.75rem; color: #5A8A70; text-align: center;">
      {footer_org} · Powered by Adar<br>
      <a href="{APP_URL}" style="color: #2EB87E;">Visit app</a>
    </div>
  </div>
</body>
</html>"""


def _btn(text: str, url: str, color: str = "#2EB87E") -> str:
    return (f'<div style="margin: 24px 0;">'
            f'<a href="{url}" style="background:{color}; color:#fff; padding:12px 24px; '
            f'border-radius:8px; text-decoration:none; font-weight:600; font-size:0.95rem;">'
            f'{text}</a></div>')


# ── Email templates ───────────────────────────────────────────────────────────

async def email_trial_started(to: str, team_name: str, trial_end_date: str, plan: str):
    """Welcome email when trial starts after checkout."""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Welcome to Adar ARCL, {team_name}! 🏏</h2>
    <p>Your <strong>30-day free trial</strong> has started on the <strong>{plan.capitalize()} plan</strong>.</p>
    <p>Here's what you can do:</p>
    <ul style="color:#1A3326; padding-left:20px;">
      <li>Ask about player stats, career history, and dismissals</li>
      <li>Get team schedules and match scorecards</li>
      <li>Search ARCL rules and umpiring guidelines</li>
      <li>Create and vote on community polls</li>
    </ul>
    <div style="background:#EBF7F1; border:1px solid #C8E8D8; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>Trial ends:</strong> {trial_end_date}<br>
      <strong>Plan:</strong> {plan.capitalize()}<br>
      <strong>After trial:</strong> Auto-renews monthly — cancel anytime
    </div>
    {_btn("Open Adar ARCL", APP_URL)}
    <p style="color:#5A8A70; font-size:0.85rem;">
      No charge until your trial ends. You can cancel anytime from the Billing section.
    </p>"""
    await send_email(to, f"Welcome to Adar ARCL — your trial has started", _base_template("Welcome", body))


async def email_trial_ending(to: str, team_name: str, trial_end_date: str, plan: str, amount: str):
    """Reminder email 3 days before trial ends."""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Your trial ends in 3 days</h2>
    <p>Hi {team_name},</p>
    <p>Your free trial ends on <strong>{trial_end_date}</strong>.</p>
    <div style="background:#FFF3E0; border:1px solid #FFCC80; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>What happens next:</strong><br>
      Your <strong>{plan.capitalize()} plan</strong> will auto-renew at
      <strong>{amount}/month</strong> on {trial_end_date}.
      Your saved card will be charged automatically.
    </div>
    <p>To continue using Adar ARCL, no action needed — you're all set.</p>
    <p>To cancel before being charged:</p>
    {_btn("Manage Billing", f"{APP_URL}?page=billing", "#5A8A70")}
    <p style="color:#5A8A70; font-size:0.85rem;">
      Questions? Reply to this email.
    </p>"""
    await send_email(to, f"Your Adar ARCL trial ends in 3 days", _base_template("Trial ending", body))


async def email_payment_succeeded(to: str, team_name: str, amount: str, next_date: str, plan: str):
    """Confirmation email after successful monthly payment."""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Payment confirmed ✓</h2>
    <p>Hi {team_name},</p>
    <p>Your payment was successful. Thank you!</p>
    <div style="background:#EBF7F1; border:1px solid #C8E8D8; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>Amount charged:</strong> {amount}<br>
      <strong>Plan:</strong> {plan.capitalize()}<br>
      <strong>Next billing date:</strong> {next_date}
    </div>
    {_btn("Open Adar ARCL", f"{APP_URL}")}
    <p style="color:#5A8A70; font-size:0.85rem;">
      View your invoice history in the <a href="{APP_URL}?page=billing" style="color:#2EB87E;">Billing section</a>.
    </p>"""
    await send_email(to, f"Payment confirmed — Adar ARCL {plan.capitalize()}", _base_template("Payment confirmed", body))


async def email_payment_failed(to: str, team_name: str, attempt: int):
    """Urgent email when payment fails."""
    grace = "We'll retry in a few days." if attempt < 3 else "This was the final attempt."
    body = f"""
    <h2 style="color:#C62828; margin-top:0;">Payment failed ⚠️</h2>
    <p>Hi {team_name},</p>
    <p>We couldn't process your payment for Adar ARCL (attempt {attempt} of 3).</p>
    <p>{grace}</p>
    <div style="background:#FFEBEE; border:1px solid #FFCDD2; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>What to do:</strong> Update your payment method to keep access.
      If payment fails 3 times your account will be suspended.
    </div>
    {_btn("Update Payment Method", f"{APP_URL}?page=billing", "#C62828")}
    <p style="color:#5A8A70; font-size:0.85rem;">
      Need help? Reply to this email.
    </p>"""
    await send_email(to, "Action required — Adar ARCL payment failed", _base_template("Payment failed", body))


async def email_subscription_cancelled(to: str, team_name: str, ends_at: str):
    """Confirmation email when subscription is cancelled."""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Subscription cancelled</h2>
    <p>Hi {team_name},</p>
    <p>Your Adar ARCL subscription has been cancelled.</p>
    <div style="background:#F5F5F5; border:1px solid #E0E0E0; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>Access until:</strong> {ends_at}<br>
      You keep full access until the end of your billing period.
    </div>
    <p>Changed your mind?</p>
    {_btn("Reactivate Subscription", f"{APP_URL}?page=billing", "#5A8A70")}
    <p style="color:#5A8A70; font-size:0.85rem;">
      We're sorry to see you go. You can resubscribe anytime.
    </p>"""
    await send_email(to, "Your Adar ARCL subscription has been cancelled", _base_template("Subscription cancelled", body))


async def send_subscription_cancelled_email(to: str, team_name: str, ends_at: str = ""):
    """Email sent when a team cancels their subscription."""
    ends_line = f"<p>You keep full access until <strong>{ends_at}</strong>.</p>" if ends_at else ""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Subscription cancelled</h2>
    <p>Hi {team_name},</p>
    <p>Your Adar ARCL subscription has been <strong>cancelled</strong>.</p>
    {ends_line}
    <div style="background:#F5F5F5; border:1px solid #E0E0E0; border-radius:8px; padding:16px; margin:20px 0;">
      You keep full access until the end of your billing period.<br>
      After that, your account will be deactivated.
    </div>
    <p>Changed your mind? You can reactivate anytime before the period ends.</p>
    {_btn("Reactivate Subscription", f"{APP_URL}?page=billing", "#5A8A70")}
    <p style="color:#5A8A70; font-size:0.85rem;">
      We're sorry to see you go. Thank you for being part of the ARCL community.
    </p>"""
    await send_email(to, "Your Adar ARCL subscription has been cancelled", _base_template("Subscription cancelled", body))


async def send_reactivation_email(to: str, team_name: str, next_billing: str = ""):
    """Email sent when a team reactivates their cancelled subscription."""
    next_line = f"<p>Your next billing date is <strong>{next_billing}</strong>.</p>" if next_billing else ""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Subscription reactivated 🎉</h2>
    <p>Hi {team_name},</p>
    <p>Great news — your Adar ARCL subscription has been <strong>reactivated</strong>.
       Your access continues uninterrupted.</p>
    {next_line}
    <p>You can manage your billing anytime from inside Adar.</p>
    {_btn("Open Adar", APP_URL)}
    <p style="color:#5A8A70; font-size:0.85rem;">
      Welcome back! We're glad you're staying.
    </p>"""
    await send_email(to, "Your Adar ARCL subscription has been reactivated", _base_template("Subscription reactivated", body))


async def send_otp_email(to: str, team_name: str, otp: str):
    """Email the 6-digit OTP login code."""
    body = f"""
    <div style="text-align:center;margin:8px 0 24px">
      <div style="font-size:0.8rem;color:#5A8A70;margin-bottom:12px;letter-spacing:0.04em;text-transform:uppercase">
        Your login code
      </div>
      <div style="font-size:2.8rem;font-weight:800;letter-spacing:0.22em;color:#1A3326;
        background:#E8F5EE;border-radius:12px;padding:16px 24px;display:inline-block;
        border:2px solid rgba(46,184,126,0.3)">
        {otp}
      </div>
      <div style="font-size:0.78rem;color:#5A8A70;margin-top:12px">
        Expires in <strong>5 minutes</strong> · Do not share this code
      </div>
    </div>
    <p style="font-size:0.85rem;color:#5A8A70;text-align:center;margin-top:0">
      If you didn't try to sign in to Adar, you can safely ignore this email.
    </p>"""
    await send_email(
        to,
        f"Your Adar login code: {otp}",
        _base_template(f"Sign in to {_BRAND['brand_name']}", f"<p>Hi <strong>{team_name}</strong>,</p>{body}")
    )


async def send_welcome_email(to: str, team_name: str, plan: str = "standard", trial_ends: str = ""):
    """Send welcome email after successful Stripe checkout."""
    trial_end_line = (
        f"<div style='background:#E8F5EE;border-left:4px solid #2EB87E;padding:12px 16px;"
        f"border-radius:6px;margin:16px 0'>"
        f"<strong>🎉 Your 30-day free trial is active</strong><br>"
        f"<span style='color:#5A8A70;font-size:0.88rem'>Trial ends: <strong>{trial_ends}</strong>"
        f" · No charge until then · Cancel anytime</span></div>"
    ) if trial_ends else (
        "<div style='background:#E8F5EE;border-left:4px solid #2EB87E;padding:12px 16px;"
        "border-radius:6px;margin:16px 0'>"
        "<strong>🎉 Your 30-day free trial is active</strong><br>"
        "<span style='color:#5A8A70;font-size:0.88rem'>No charge for 30 days · Cancel anytime</span></div>"
    )

    subject = f"Welcome to Adar ARCL, {team_name}! 🏏"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1A3326">
      <div style="background:#2EB87E;padding:24px;border-radius:12px 12px 0 0;text-align:center">
        <div style="width:52px;height:52px;background:#fff;border-radius:14px;display:inline-flex;
          align-items:center;justify-content:center;font-size:1.1rem;font-weight:700;
          color:#2EB87E;margin-bottom:12px">আদর</div>
        <h1 style="color:#fff;margin:0;font-size:1.4rem">Welcome to Adar ARCL!</h1>
        <p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:0.9rem">
          Your AI cricket assistant is ready
        </p>
      </div>
      <div style="background:#F5FBF7;padding:28px;border-radius:0 0 12px 12px;
        border:1px solid #C8E8D8;border-top:none">
        <p>Hi <strong>{team_name}</strong>,</p>
        <p>Your Adar ARCL account is all set up and ready to go.</p>
        {trial_end_line}
        <p style="font-weight:600;margin-bottom:8px">Try asking Adar:</p>
        <ul style="padding-left:20px;color:#5A8A70;line-height:2.2">
          <li>Show our batting stats for Spring 2026</li>
          <li>What is the wide rule in men's league?</li>
          <li>Show our schedule and umpiring assignments</li>
          <li>How was [player name] dismissed this season?</li>
          <li>Top 5 batsmen in Div H</li>
        </ul>
        <div style="text-align:center;margin:24px 0">
          <a href="{APP_URL}"
            style="background:#2EB87E;color:#fff;padding:12px 28px;border-radius:10px;
            text-decoration:none;font-weight:600;font-size:1rem">
            Open Adar →
          </a>
        </div>
        <p style="font-size:0.82rem;color:#5A8A70;text-align:center">
          Manage billing at any time from the Billing page inside Adar.<br>
          Questions? Reply to this email — we're happy to help.
        </p>
      </div>
    </div>
    """
    await send_email(to, subject, html)


async def send_trial_ending_email(to: str, team_name: str, trial_ends: str, plan: str = "standard"):
    """Send reminder 3 days before trial ends (triggered by Stripe trial_will_end event)."""
    plan_names = {"basic": "$10/mo", "standard": "$15/mo", "unlimited": "$30/mo"}
    amount = plan_names.get(plan, "$15/mo")

    subject = f"Your Adar trial ends in 3 days — {team_name}"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1A3326">
      <div style="background:#EF9F27;padding:24px;border-radius:12px 12px 0 0;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:1.3rem">⏰ Trial ending soon</h1>
      </div>
      <div style="background:#F5FBF7;padding:28px;border-radius:0 0 12px 12px;border:1px solid #C8E8D8;border-top:none">
        <p>Hi <strong>{team_name}</strong>,</p>
        <p>Your Adar free trial ends on <strong>{trial_ends[:10]}</strong>.</p>
        <p>After that you'll be charged <strong>{amount}</strong> automatically — no action needed.</p>
        <p>To cancel before being charged:</p>
        <ol style="color:#5A8A70">
          <li>Log in to Adar</li>
          <li>Click 💳 Billing</li>
          <li>Click Cancel subscription</li>
        </ol>
        <div style="text-align:center;margin:20px 0">
          <a href="{APP_URL}"
            style="background:#2EB87E;color:#fff;padding:12px 28px;border-radius:10px;text-decoration:none;font-weight:600">
            Manage billing →
          </a>
        </div>
      </div>
    </div>
    """
    await send_email(to, subject, html)



async def send_appointment_confirmation_email(
    to: str,
    caller_name: str,
    practice_name: str,
    appointment_type_name: str,
    provider_name: str,
    when_formatted: str,
    appointment_id: str,
):
    """Email sent when a scheduling appointment is confirmed via confirm_booking.
    Domain-neutral (practice_name comes from the caller, not hardcoded ARCL
    copy) — see domains/scheduling/tools/availability_tools.py."""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Appointment confirmed ✓</h2>
    <p>Hi {caller_name},</p>
    <p>Your appointment with <strong>{practice_name}</strong> is confirmed.</p>
    <div style="background:#EBF7F1; border:1px solid #C8E8D8; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>When:</strong> {when_formatted}<br>
      <strong>Provider:</strong> {provider_name}<br>
      <strong>Visit type:</strong> {appointment_type_name}<br>
      <strong>Confirmation ID:</strong> {appointment_id[:8]}
    </div>
    <p style="color:#5A8A70; font-size:0.85rem;">
      Need to reschedule or cancel? Just message the assistant with your phone
      number and this confirmation ID.
    </p>"""
    await send_email(
        to,
        f"Appointment confirmed — {when_formatted}",
        _base_template(
            "Appointment confirmed",
            body,
            logo_text="Adar",
            brand_name="Adar Scheduling",
            footer_org="Practice Scheduling Assistant",
        ),
    )


async def send_appointment_cancelled_email(
    to: str,
    caller_name: str,
    practice_name: str,
    appointment_type_name: str,
    provider_name: str,
    when_formatted: str,
    appointment_id: str,
    cancel_reason: str = "",
):
    """Email sent to the caller when their appointment is cancelled via
    cancel_appointment (including the cancel-then-rebook path inside
    reschedule_appointment). Best-effort, mirrors
    send_appointment_confirmation_email's template and call convention —
    see domains/scheduling/tools/availability_tools.py."""
    reason_line = f"<br><strong>Reason:</strong> {cancel_reason}" if cancel_reason else ""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">Appointment cancelled</h2>
    <p>Hi {caller_name},</p>
    <p>Your appointment with <strong>{practice_name}</strong> has been cancelled.</p>
    <div style="background:#EBF7F1; border:1px solid #C8E8D8; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>Was scheduled:</strong> {when_formatted}<br>
      <strong>Provider:</strong> {provider_name}<br>
      <strong>Visit type:</strong> {appointment_type_name}<br>
      <strong>Confirmation ID:</strong> {appointment_id[:8]}{reason_line}
    </div>
    <p style="color:#5A8A70; font-size:0.85rem;">
      Want to book a new time instead? Just message the assistant.
    </p>"""
    await send_email(
        to,
        f"Appointment cancelled — {when_formatted}",
        _base_template(
            "Appointment cancelled",
            body,
            logo_text="Adar",
            brand_name="Adar Scheduling",
            footer_org="Practice Scheduling Assistant",
        ),
    )


async def send_new_booking_notification_email(
    to: str,
    practice_name: str,
    caller_name: str,
    caller_phone: str,
    appointment_type_name: str,
    provider_name: str,
    when_formatted: str,
    appointment_id: str,
    caller_email: str = "",
    reason: str = "",
):
    """Staff-facing email sent to the practice's notification_email (falling
    back to the platform ADMIN_EMAIL when a practice hasn't set one) the
    moment confirm_booking succeeds, so front-desk staff learn about a new
    booking without having to open the admin calendar. Best-effort — never
    blocks or fails the booking itself. See
    domains/scheduling/tools/availability_tools.py."""
    contact_line = caller_phone
    if caller_email:
        contact_line += f" · {caller_email}"
    reason_line = f"<br><strong>Reason for visit:</strong> {reason}" if reason else ""
    body = f"""
    <h2 style="color:#1A3326; margin-top:0;">New booking</h2>
    <p>A new appointment was just booked at <strong>{practice_name}</strong> through Adar Front Desk.</p>
    <div style="background:#EBF7F1; border:1px solid #C8E8D8; border-radius:8px; padding:16px; margin:20px 0;">
      <strong>When:</strong> {when_formatted}<br>
      <strong>Provider:</strong> {provider_name}<br>
      <strong>Visit type:</strong> {appointment_type_name}<br>
      <strong>Patient:</strong> {caller_name}<br>
      <strong>Contact:</strong> {contact_line}<br>
      <strong>Confirmation ID:</strong> {appointment_id[:8]}{reason_line}
    </div>
    <p style="color:#5A8A70; font-size:0.85rem;">
      This booking is already on the live calendar in the admin console.
    </p>"""
    await send_email(
        to,
        f"New booking — {caller_name} with {provider_name}, {when_formatted}",
        _base_template(
            "New booking",
            body,
            logo_text="Adar",
            brand_name="Adar Scheduling",
            footer_org="Practice Scheduling Assistant",
        ),
    )
