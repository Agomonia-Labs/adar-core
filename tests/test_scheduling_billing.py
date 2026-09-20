import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.routes import payments


class SchedulingBillingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.domain_patch = patch.object(payments, "DOMAIN", "scheduling")
        self.environment_patch = patch.dict(
            os.environ,
            {
                "STRIPE_PRICE_FRONT_DESK_MONTHLY": "price_front_desk_monthly",
                "STRIPE_PRICE_FRONT_DESK_YEARLY": "price_front_desk_yearly",
            },
        )
        self.domain_patch.start()
        self.environment_patch.start()
        self.plans = payments._plan_catalogue()

    def tearDown(self):
        self.environment_patch.stop()
        self.domain_patch.stop()

    def test_catalogue_has_exact_front_desk_prices(self):
        self.assertEqual(
            self.plans["monthly"],
            {
                "name": "ADAR Front Desk Monthly",
                "price_id": "price_front_desk_monthly",
                "trial_days": 0,
                "quota": 500,
                "description": "$50/month",
                "amount": 5000,
                "currency": "usd",
                "interval": "month",
            },
        )
        self.assertEqual(self.plans["yearly"]["amount"], 45000)
        self.assertEqual(self.plans["yearly"]["interval"], "year")

    async def test_public_plans_include_monthly_and_yearly(self):
        result = await payments.get_plans()

        self.assertEqual(result["domain"], "scheduling")
        self.assertEqual(
            [(plan["id"], plan["amount"], plan["interval"]) for plan in result["plans"]],
            [("monthly", 5000, "month"), ("yearly", 45000, "year")],
        )

    async def test_activation_requires_verified_checkout_session(self):
        with patch.dict(os.environ, {"BILLING_ENABLED": "true"}):
            with self.assertRaises(HTTPException) as error:
                await payments.activate(team={"team_id": "practice-owner"})

        self.assertEqual(error.exception.status_code, 400)

    async def test_activation_verifies_subscription_and_sends_email_once(self):
        session = SimpleNamespace(
            metadata={"team_id": "practice-owner", "domain": "scheduling", "plan": "monthly"},
            status="complete",
            payment_status="paid",
            subscription="sub_front_desk",
            customer="cus_front_desk",
        )
        subscription = SimpleNamespace(status="active")
        team_db = {
            "team_id": "practice-owner",
            "team_name": "Riverside Family Medicine",
            "email": "owner@example.com",
            "stripe_customer_id": "cus_front_desk",
        }
        update_team = AsyncMock()
        send_email = AsyncMock(return_value=True)

        with patch.dict(os.environ, {"BILLING_ENABLED": "true"}), \
             patch.object(payments, "_get_team_from_db", AsyncMock(return_value=team_db)), \
             patch.object(payments, "_update_team", update_team), \
             patch.object(payments.stripe.checkout.Session, "retrieve", return_value=session), \
             patch.object(payments.stripe.Subscription, "retrieve", return_value=subscription), \
             patch("src.adar.notify.send_welcome_email", send_email):
            result = await payments.activate(
                session_id="cs_verified",
                team={"team_id": "practice-owner", "status": "pending_payment"},
            )

        self.assertEqual(result["status"], "activated")
        self.assertTrue(result["email_sent"])
        send_email.assert_awaited_once()
        self.assertTrue(any(
            call.args[1].get("subscription_status") == "active"
            and call.args[1].get("stripe_subscription_id") == "sub_front_desk"
            for call in update_team.await_args_list
        ))

    def test_price_validation_accepts_expected_stripe_price(self):
        price = {
            "currency": "usd",
            "unit_amount": 5000,
            "active": True,
            "recurring": {"interval": "month"},
        }
        with patch.object(payments.stripe.Price, "retrieve", return_value=price):
            payments._validate_plan_price("monthly", self.plans["monthly"])

    def test_price_validation_accepts_stripe_recurring_object(self):
        class StripeRecurring:
            def to_dict(self):
                return {"interval": "month"}

            def __iter__(self):
                raise TypeError("Stripe resources are not directly iterable")

        price = SimpleNamespace(
            currency="usd",
            unit_amount=5000,
            active=True,
            recurring=StripeRecurring(),
        )
        with patch.object(payments.stripe.Price, "retrieve", return_value=price):
            payments._validate_plan_price("monthly", self.plans["monthly"])

    def test_price_validation_rejects_wrong_amount(self):
        price = {
            "currency": "usd",
            "unit_amount": 500,
            "active": True,
            "recurring": {"interval": "month"},
        }
        with patch.object(payments.stripe.Price, "retrieve", return_value=price):
            with self.assertRaises(HTTPException) as error:
                payments._validate_plan_price("monthly", self.plans["monthly"])

        self.assertEqual(error.exception.status_code, 503)

    def test_subscription_price_wins_over_stale_metadata(self):
        subscription = {
            "metadata": {"plan": "monthly"},
            "items": {"data": [{"price": {"id": "price_front_desk_yearly"}}]},
        }

        self.assertEqual(payments._plan_key_from_subscription(subscription), "yearly")


if __name__ == "__main__":
    unittest.main()
