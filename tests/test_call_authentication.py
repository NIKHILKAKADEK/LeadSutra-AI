"""Exercise real Bearer dependencies with isolated data and mocked dispatch."""

import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from app.app import app
from app.core.config import Settings
from app.schemas.calling_eligibility import EligibilityResponse, utc_now
from app.schemas.call_dispatch import DispatchResult


ADMIN = "fixture-admin-" + "a" * 32
REVIEWER = "fixture-reviewer-" + "r" * 32
PHONE = "+919876543210"


class CallAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = Settings(
            _env_file=None, eligibility_admin_token=ADMIN,
            eligibility_reviewer_token=REVIEWER, outbound_calls_enabled=False,
        )
        self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility.get_settings", return_value=self.settings,
        ))
        store = Mock()
        store.get_consent.return_value = None
        self.store = self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility._store", return_value=store,
        ))
        self.leads = self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility.LeadJsonService",
        ))
        self.leads.return_value.load.return_value = []
        self.evaluate = self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility.evaluate_eligibility",
            return_value=EligibilityResponse(
                eligible=False, reason_codes=["fixture"], checked_at=utc_now(),
                lead_id="auth-fixture", normalized_phone_number=PHONE,
            ),
        ))
        self.dispatch = self.stack.enter_context(patch(
            "app.api.v1.calls.dispatch_voice_call",
            return_value=DispatchResult(
                status="dry_run", eligible=True, dispatched=False,
                dispatch_enabled=False, lead_id="auth-fixture",
                normalized_phone_number=PHONE,
            ),
        ))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)

    async def request_all(self, authorization):
        headers = {"Authorization": authorization} if authorization is not None else {}
        consent = await self.client.get(
            "/api/v1/calling-eligibility/consent/auth-fixture",
            params={"phone_number": PHONE}, headers=headers,
        )
        eligibility = await self.client.get(
            "/api/v1/calling-eligibility/auth-fixture",
            params={"phone_number": PHONE}, headers=headers,
        )
        dispatch = await self.client.post(
            "/api/v1/calls/dispatch", headers=headers,
            json={"lead_id": "auth-fixture", "phone_number": PHONE,
                  "idempotency_key": str(uuid4())},
        )
        return [consent, eligibility, dispatch]

    async def test_admin_accesses_all_three_with_distinct_reviewer_configured(self):
        responses = await self.request_all("Bearer " + ADMIN)
        self.assertEqual([response.status_code for response in responses], [200, 200, 200])
        self.evaluate.assert_called_once()
        self.dispatch.assert_called_once()

    async def test_reviewer_can_only_preview_eligibility(self):
        responses = await self.request_all("Bearer " + REVIEWER)
        self.assertEqual([response.status_code for response in responses], [401, 200, 401])
        self.dispatch.assert_not_called()
        self.evaluate.assert_called_once()
        # Only the authorized eligibility preview may load a store.
        self.store.assert_called_once()

    async def test_missing_invalid_or_malformed_tokens_never_reach_handlers(self):
        for authorization in [None, "", "Bearer", "Basic " + ADMIN,
                              "Bearer wrong-token", "Bearer " + ADMIN[:-1],
                              "Bearer Bearer " + ADMIN]:
            with self.subTest(authorization_kind=(authorization or "missing").split()[0]):
                responses = await self.request_all(authorization)
                self.assertEqual([response.status_code for response in responses], [401, 401, 401])
                for response in responses:
                    self.assertEqual(response.headers.get("www-authenticate"), "Bearer")
                    self.assertEqual(response.json()["detail"], "Authentication required.")
        self.store.assert_not_called()
        self.leads.assert_not_called()
        self.evaluate.assert_not_called()
        self.dispatch.assert_not_called()

    async def test_bearer_scheme_is_case_insensitive(self):
        responses = await self.request_all("bEaReR " + ADMIN)
        self.assertEqual([response.status_code for response in responses], [200, 200, 200])

    async def test_unset_reviewer_keeps_existing_admin_fallback(self):
        for reviewer in [None, ""]:
            self.settings.eligibility_reviewer_token = reviewer
            responses = await self.request_all("Bearer " + ADMIN)
            self.assertEqual([response.status_code for response in responses], [200, 200, 200])

    async def test_missing_or_short_auth_configuration_still_fails_closed(self):
        self.settings.eligibility_reviewer_token = None
        for admin in [None, "", "short"]:
            self.settings.eligibility_admin_token = admin
            responses = await self.request_all("Bearer " + ADMIN)
            self.assertEqual([response.status_code for response in responses], [503, 503, 503])
        self.dispatch.assert_not_called()

    async def test_short_reviewer_does_not_bypass_configuration_validation(self):
        self.settings.eligibility_reviewer_token = "short"
        responses = await self.request_all("Bearer " + ADMIN)
        self.assertEqual([response.status_code for response in responses], [200, 503, 200])
        self.evaluate.assert_not_called()

    async def test_same_swagger_security_scheme_on_all_three_routes(self):
        schema = (await self.client.get("/openapi.json")).json()
        for path, method in [
            ("/api/v1/calling-eligibility/consent/{lead_id}", "get"),
            ("/api/v1/calling-eligibility/{lead_id}", "get"),
            ("/api/v1/calls/dispatch", "post"),
        ]:
            self.assertEqual(schema["paths"][path][method]["security"], [{"LeadSutraBearer": []}])


class AuthenticationSettingsTests(unittest.TestCase):
    def test_env_overrides_dotenv_without_changing_either_token(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text(
                f"ELIGIBILITY_ADMIN_TOKEN={ADMIN}\nELIGIBILITY_REVIEWER_TOKEN={REVIEWER}\n",
                encoding="utf-8",
            )
            settings = Settings(_env_file=path)
            self.assertEqual(settings.eligibility_admin_token, ADMIN)
            self.assertEqual(settings.eligibility_reviewer_token, REVIEWER)
            override = "process-fixture-" + "p" * 32
            with patch.dict(os.environ, {"ELIGIBILITY_ADMIN_TOKEN": override}):
                settings = Settings(_env_file=path)
                self.assertEqual(settings.eligibility_admin_token, override)
                self.assertEqual(settings.eligibility_reviewer_token, REVIEWER)
            self.assertIn(ADMIN, path.read_text(encoding="utf-8"))
