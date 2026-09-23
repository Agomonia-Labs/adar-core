import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response

from api.routes import geetabitan_guest
from api.routes.auth import decode_token


class GeetabitanGuestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET": "unit-test-secret",
                "GEETABITAN_GUEST_ACCESS_ENABLED": "true",
                "GEETABITAN_GUEST_VOICE_ENABLED": "true",
            },
        )
        self.domain = patch.object(geetabitan_guest.settings, "DOMAIN", "geetabitan")
        self.environment.start()
        self.domain.start()
        geetabitan_guest.clear_test_state()

    def tearDown(self):
        geetabitan_guest.clear_test_state()
        self.domain.stop()
        self.environment.stop()

    def test_guest_token_is_short_lived_and_domain_scoped(self):
        token, guest_id, expires_at = geetabitan_guest.issue_guest_token()
        claims = decode_token(token)

        self.assertEqual(claims["sub"], guest_id)
        self.assertEqual(claims["role"], geetabitan_guest.GUEST_ROLE)
        self.assertEqual(claims["token_use"], geetabitan_guest.GUEST_TOKEN_USE)
        self.assertEqual(claims["domain"], "geetabitan")
        self.assertEqual(
            claims["scope"],
            ["geetabitan:query", "geetabitan:voice", "geetabitan:session"],
        )
        self.assertLessEqual(
            int(claims["exp"]) - int(datetime.now(timezone.utc).timestamp()),
            geetabitan_guest.GUEST_TOKEN_TTL_SECONDS,
        )
        self.assertGreater(expires_at, datetime.now(timezone.utc))

    async def test_session_requires_no_login_and_disables_caching(self):
        request = SimpleNamespace(
            headers={"origin": "https://labs.agomoniai.com"},
            client=SimpleNamespace(host="203.0.113.10"),
        )
        response = Response()
        result = await geetabitan_guest.create_guest_session(request, response)

        self.assertEqual(result["token_type"], "bearer")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            decode_token(result["access_token"])["role"],
            geetabitan_guest.GUEST_ROLE,
        )

    async def test_normal_user_token_is_rejected(self):
        from jose import jwt

        token = jwt.encode(
            {
                "team_id": "customer-team",
                "sub": "customer-team",
                "role": "user",
                "domain": "geetabitan",
                "exp": datetime.now(timezone.utc).timestamp() + 300,
            },
            os.environ["JWT_SECRET"],
            algorithm="HS256",
        )
        with self.assertRaises(HTTPException) as error:
            await geetabitan_guest.get_geetabitan_guest(
                credentials=SimpleNamespace(credentials=token),
            )
        self.assertEqual(error.exception.status_code, 403)

    async def test_unapproved_browser_origin_is_rejected(self):
        request = SimpleNamespace(
            headers={"origin": "https://untrusted.example"},
            client=SimpleNamespace(host="203.0.113.10"),
        )
        with self.assertRaises(HTTPException) as error:
            await geetabitan_guest.create_guest_session(request, Response())
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(geetabitan_guest._session_windows, {})

    async def test_query_limit_is_bound_to_guest_token(self):
        claims = decode_token(geetabitan_guest.issue_guest_token()[0])
        for _ in range(geetabitan_guest.GUEST_QUERY_WINDOW_LIMIT):
            await geetabitan_guest.enforce_query_rate_limit(claims)

        with self.assertRaises(HTTPException) as error:
            await geetabitan_guest.enforce_query_rate_limit(claims)
        self.assertEqual(error.exception.status_code, 429)
        self.assertIn("Retry-After", error.exception.headers)

    async def test_capabilities_are_public_and_bengali_first(self):
        claims = decode_token(geetabitan_guest.issue_guest_token()[0])
        capabilities = await geetabitan_guest.get_guest_capabilities(claims)

        self.assertEqual(capabilities["domain"], "geetabitan")
        self.assertEqual(capabilities["languages"][0]["code"], "bn-IN")
        self.assertTrue(capabilities["voice_enabled"])
        self.assertNotIn("admin", " ".join(capabilities["features"]).lower())

    async def test_guest_chat_overrides_identity_and_skips_account_billing(self):
        from api import main
        from api.schemas import ChatRequest, ChatResponse

        guest = decode_token(geetabitan_guest.issue_guest_token()[0])
        expected = ChatResponse(
            response="গীতবিতান থেকে একটি উত্তর",
            session_id="session-1",
            user_id=guest["sub"],
            eval=None,
        )
        execute = AsyncMock(return_value=expected)
        with patch.object(main, "_execute_chat", execute), patch.object(
            main, "enforce_geetabitan_guest_query_rate_limit", AsyncMock()
        ):
            result = await main.geetabitan_guest_chat(
                ChatRequest(message="একলা চলো রে গানের অর্থ কী?", user_id="spoofed-user"),
                SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1")),
                guest,
            )

        self.assertEqual(result.user_id, guest["sub"])
        scoped_request = execute.await_args.args[0]
        self.assertEqual(scoped_request.user_id, guest["sub"])
        self.assertFalse(execute.await_args.kwargs["track_account_usage"])
        self.assertFalse(execute.await_args.kwargs["run_evaluation"])


if __name__ == "__main__":
    unittest.main()
