import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response

from api.routes import scheduling_guest
from api.routes.auth import decode_token
from api.routes.scheduling_admin import get_scheduling_staff


class SchedulingGuestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET": "unit-test-secret",
                "SCHEDULING_GUEST_ACCESS_ENABLED": "true",
                "SCHEDULING_GUEST_PRACTICE_ID": "demo-practice",
                "SCHEDULING_GUEST_PRACTICE_IDS": "demo-practice",
            },
        )
        self.domain = patch.object(scheduling_guest.settings, "DOMAIN", "scheduling")
        self.environment.start()
        self.domain.start()
        scheduling_guest._token_windows.clear()

    def tearDown(self):
        scheduling_guest._token_windows.clear()
        self.domain.stop()
        self.environment.stop()

    def test_guest_token_is_short_lived_and_practice_scoped(self):
        token, guest_id, expires_at = scheduling_guest._issue_guest_token("demo-practice")
        claims = decode_token(token)

        self.assertEqual(claims["team_id"], guest_id)
        self.assertEqual(claims["role"], scheduling_guest.GUEST_ROLE)
        self.assertEqual(claims["token_use"], scheduling_guest.GUEST_TOKEN_USE)
        self.assertEqual(claims["practice_id"], "demo-practice")
        self.assertEqual(claims["practice_ids"], ["demo-practice"])
        self.assertLessEqual(
            int(claims["exp"]) - int(datetime.now(timezone.utc).timestamp()),
            scheduling_guest.GUEST_TOKEN_TTL_SECONDS,
        )
        self.assertGreater(expires_at, datetime.now(timezone.utc))

    def test_overlap_detection_rejects_only_intersecting_slots(self):
        first_start = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)
        first_end = datetime(2026, 10, 1, 17, 30, tzinfo=timezone.utc)
        self.assertTrue(scheduling_guest._overlaps(
            first_start,
            first_end,
            datetime(2026, 10, 1, 17, 15, tzinfo=timezone.utc),
            datetime(2026, 10, 1, 17, 45, tzinfo=timezone.utc),
        ))
        self.assertFalse(scheduling_guest._overlaps(
            first_start,
            first_end,
            datetime(2026, 10, 1, 17, 30, tzinfo=timezone.utc),
            datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc),
        ))

    async def test_guest_token_is_accepted_only_by_guest_dependency(self):
        token, _, _ = scheduling_guest._issue_guest_token("demo-practice")
        claims = await scheduling_guest.get_scheduling_guest(
            credentials=SimpleNamespace(credentials=token),
        )
        self.assertEqual(claims["practice_id"], "demo-practice")

        with self.assertRaises(HTTPException) as error:
            await get_scheduling_staff(team=claims)
        self.assertEqual(error.exception.status_code, 403)

    async def test_guest_dependency_rejects_a_staff_token_shape(self):
        from jose import jwt

        token = jwt.encode(
            {
                "team_id": "staff",
                "role": "practice_staff",
                "practice_id": "demo-practice",
                "exp": datetime.now(timezone.utc).timestamp() + 300,
            },
            os.environ["JWT_SECRET"],
            algorithm="HS256",
        )
        with self.assertRaises(HTTPException) as error:
            await scheduling_guest.get_scheduling_guest(
                credentials=SimpleNamespace(credentials=token),
            )
        self.assertEqual(error.exception.status_code, 403)

    async def test_session_endpoint_returns_viewer_token_without_login(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        response = Response()
        with patch.object(scheduling_guest, "_active_practice", AsyncMock(return_value=object())), \
             patch.object(scheduling_guest, "_db", return_value=object()):
            result = await scheduling_guest.create_guest_session(request, response)

        self.assertEqual(result["token_type"], "bearer")
        self.assertEqual(result["practice_id"], "demo-practice")
        self.assertEqual(result["expires_in"], scheduling_guest.GUEST_TOKEN_TTL_SECONDS)
        self.assertEqual(response.headers["cache-control"], "no-store")
        claims = decode_token(result["access_token"])
        self.assertEqual(claims["role"], scheduling_guest.GUEST_ROLE)

    async def test_session_issuance_is_rate_limited_per_viewer_ip(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.8"))
        for _ in range(scheduling_guest.GUEST_TOKEN_WINDOW_LIMIT):
            await scheduling_guest._enforce_token_rate_limit(request)

        with self.assertRaises(HTTPException) as error:
            await scheduling_guest._enforce_token_rate_limit(request)
        self.assertEqual(error.exception.status_code, 429)
        self.assertIn("Retry-After", error.exception.headers)

    async def test_local_and_production_origins_have_separate_rate_limits(self):
        local_request = SimpleNamespace(
            headers={"origin": "http://localhost:4177"},
            client=SimpleNamespace(host="203.0.113.8"),
        )
        production_request = SimpleNamespace(
            headers={"origin": "https://labs.agomoniai.com"},
            client=SimpleNamespace(host="203.0.113.8"),
        )
        for _ in range(scheduling_guest.GUEST_TOKEN_WINDOW_LIMIT):
            await scheduling_guest._enforce_token_rate_limit(local_request)

        await scheduling_guest._enforce_token_rate_limit(production_request)

    async def test_file_origin_is_rejected_before_rate_limit_accounting(self):
        request = SimpleNamespace(
            headers={"origin": "null"},
            client=SimpleNamespace(host="203.0.113.8"),
        )
        response = Response()
        with self.assertRaises(HTTPException) as error:
            await scheduling_guest.create_guest_session(request, response)

        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(scheduling_guest._token_windows, {})

    async def test_guest_token_can_select_only_configured_demo_practices(self):
        with patch.dict(os.environ, {
            "SCHEDULING_GUEST_PRACTICE_IDS": "demo-health,demo-salon",
        }):
            token, _, _ = scheduling_guest._issue_guest_token(["demo-health", "demo-salon"])
            claims = await scheduling_guest.get_scheduling_guest(
                credentials=SimpleNamespace(credentials=token),
            )
            self.assertEqual(
                scheduling_guest._resolve_guest_practice(claims, "demo-salon"),
                "demo-salon",
            )
            with self.assertRaises(HTTPException) as error:
                scheduling_guest._resolve_guest_practice(claims, "private-practice")
            self.assertEqual(error.exception.status_code, 403)

    async def test_session_returns_all_configured_demo_practices(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        response = Response()
        with patch.dict(os.environ, {
            "SCHEDULING_GUEST_PRACTICE_IDS": "demo-health,demo-salon",
        }), patch.object(scheduling_guest, "_active_practice", AsyncMock(return_value=object())), \
             patch.object(scheduling_guest, "_db", return_value=object()):
            result = await scheduling_guest.create_guest_session(request, response)

        self.assertEqual(result["practice_id"], "demo-health")
        self.assertEqual(result["practice_ids"], ["demo-health", "demo-salon"])


if __name__ == "__main__":
    unittest.main()
