# ADAR Front Desk Billing

ADAR Front Desk uses the shared `adar-core` Stripe billing engine with two
flat-rate recurring subscriptions:

| Plan | Price | Stripe runtime variable |
| --- | ---: | --- |
| Monthly | $50 USD per month | `STRIPE_PRICE_FRONT_DESK_MONTHLY` |
| Yearly | $450 USD per year | `STRIPE_PRICE_FRONT_DESK_YEARLY` |

The yearly plan saves $150 compared with twelve monthly payments. Usage limits
remain on the existing scheduling defaults until product limits are defined.

## 1. Create Stripe products and prices

For the production scheduling deployment, create these in Stripe live mode.
Use separate test-mode Prices only in a non-production environment.

1. Create the product `ADAR Front Desk`.
2. Add an active recurring Price for `$50.00 USD` every month.
3. Add an active recurring Price for `$450.00 USD` every year.
4. Copy both `price_...` identifiers.

The checkout endpoint retrieves the selected Stripe Price and rejects checkout
when its amount, currency, interval, or active state differs from this catalog.
The production deployment performs the same validation before building or
deploying and requires live-mode Prices.

## 2. Create and populate GCP secrets

The scheduling deployment reuses the existing `stripe-secret-key` and uses
three scheduling-specific secrets:

```bash
cd /Users/brajadas/project/adar-core
bash infra/create_scheduling_secrets.sh
```

Add the two Price identifiers:

```bash
PROJECT_ID=bdas-493785

read -r -p "Front Desk monthly Stripe price ID: " VALUE
printf %s "$VALUE" | gcloud secrets versions add \
  scheduling-stripe-price-monthly --data-file=- --project="$PROJECT_ID"

read -r -p "Front Desk yearly Stripe price ID: " VALUE
printf %s "$VALUE" | gcloud secrets versions add \
  scheduling-stripe-price-yearly --data-file=- --project="$PROJECT_ID"
```

## 3. Configure the Stripe webhook

Create a Stripe event destination for:

```text
https://api.scheduling.adar.agomoniai.com/api/payments/webhook
```

Subscribe to:

- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

Store its `whsec_...` signing secret:

```bash
read -r -p "Scheduling Stripe webhook secret: " VALUE
printf %s "$VALUE" | gcloud secrets versions add \
  scheduling-stripe-webhook-secret --data-file=- --project="$PROJECT_ID"
```

## 4. Configure Stripe Customer Portal

Enable payment-method updates, cancellation, invoice history, and switching
between the Front Desk monthly and yearly prices. Do not enable unrelated ADAR
products as valid subscription switches for this portal configuration.

## 5. Deploy

The deployment script now sets `BILLING_ENABLED=true` and maps all four Stripe
runtime secrets:

```bash
cd /Users/brajadas/project/adar-core
bash infra/deploy-scheduling.sh
```

Build and deploy the scheduling frontend using its existing hosting process
with `VITE_DOMAIN=scheduling` and the production scheduling API URL.

## 6. End-to-end test

1. Confirm `GET /api/payments/plans` returns `monthly` at `5000` cents and
   `yearly` at `45000` cents.
2. Register a new practice-owner account and confirm its status is
   `pending_payment`.
3. Sign in and verify the application opens the plan selection screen.
4. Select Monthly and confirm Stripe Checkout displays `$50/month`.
5. Complete checkout and verify Front Desk shows `Subscription is active`,
   confirms whether the activation email was sent, and asks the customer to
   sign in again. The customer must not return to plan selection.
6. Repeat with a new test account and Yearly; verify `$450/year`.
7. Open Billing and confirm invoices and the renewal date are displayed.
8. Switch intervals in Stripe Customer Portal and verify the webhook updates
   `subscription_plan` in Firestore.
9. Schedule, reschedule, and cancel an appointment to confirm billing did not
   regress the scheduling workflow.
10. Create a practice staff account and verify it is active without a separate
    checkout because it belongs to the subscribed practice.

The activation endpoint verifies the Checkout Session and its Stripe
Subscription, records the customer/subscription identifiers in Firestore, and
uses the Checkout Session ID to prevent duplicate confirmation emails after a
refresh.

Before going live, recreate both Prices and the webhook in Stripe live mode,
add the live IDs and signing secret as new Secret Manager versions, redeploy,
and perform one controlled live subscription test.
