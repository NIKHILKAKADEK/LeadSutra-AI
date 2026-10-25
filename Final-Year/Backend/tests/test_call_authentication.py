"""Call routes use workspace sessions; consent changes remain admin-only."""

import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from app.app import app
from app.auth import get_current_user
from app.core.config import Settings
from app.schemas.call_dispatch import DispatchResult
from app.schemas.calling_eligibility import EligibilityResponse, utc_now

ADMIN = "fixture-admin-" + "a" * 32
REVIEWER = "fixture-reviewer-" + "r" * 32
PHONE = "+919876543210"


class CallAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.previous_user_dependency = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = lambda: {
            "_id": "fixture-user",
            "email": "fixture@example.test",
        }
        self.addCleanup(self._restore_user_dependency)
        self.settings = Settings(
            _env_file=None,
            eligibility_admin_token=ADMIN,
            eligibility_reviewer_token=REVIEWER,
            outbound_calls_enabled=False,
        )
        self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility.get_settings",
            return_value=self.settings,
        ))
        store = Mock()
        store.get_consent.return_value = None
        self.store = self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility._store",
            return_value=store,
        ))
        leads = self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility.LeadJsonService",
        ))
        leads.return_value.load.return_value = []
        self.evaluate = self.stack.enter_context(patch(
            "app.api.v1.calling_eligibility.evaluate_eligibility",
            return_value=EligibilityResponse(
                eligible=True,
                reason_codes=[],
                checked_at=utc_now(),
                lead_id="auth-fixture",
                normalized_phone_number=PHONE,
            ),
        ))
        self.dispatch = self.stack.enter_context(patch(
            "app.api.v1.calls.dispatch_voice_call",
            return_value=DispatchResult(
                status="dry_run",
                eligible=True,
                dispatched=False,
                dispatch_enabled=False,
                lead_id="auth-fixture",
                normalized_phone_number=PHONE,
            ),
        ))
        history = Mock()
        history.list_records.return_value = ([], 0)
        history.get_record.return_value = None
        self.stack.enter_context(patch(
            "app.api.v1.calls.DispatchLedger",
            return_value=history,
        ))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)

    def _restore_user_dependency(self):
        if self.previous_user_dependency is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = self.previous_user_dependency

    async def test_signed_in_user_can_check_eligibility_history_and_dispatch(self):
        eligibility = await self.client.get(
            "/api/v1/calling-eligibility/auth-fixture",
            params={"phone_number": PHONE},
        )
        history = await self.client.get("/api/v1/calls")
        dispatch = await self.client.post(
            "/api/v1/calls/dispatch",
            json={
                "lead_id": "auth-fixture",
                "phone_number": PHONE,
                "idempotency_key": str(uuid4()),
                "confirmed": True,
            },
        )
        self.assertEqual(eligibility.status_code, 200)
        self.assertTrue(eligibility.json()["eligible"])
        self.assertEqual(history.status_code, 200)
        self.assertEqual(dispatch.status_code, 200)
        self.evaluate.assert_called_once()
        self.dispatch.assert_called_once()

    async def test_dispatch_requires_explicit_confirmation(self):
        payload = {
            "lead_id": "auth-fixture",
            "phone_number": PHONE,
            "idempotency_key": str(uuid4()),
        }
        missing = await self.client.post("/api/v1/calls/dispatch", json=payload)
        declined = await self.client.post(
            "/api/v1/calls/dispatch",
            json=payload | {"confirmed": False},
        )
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(declined.status_code, 422)
        self.dispatch.assert_not_called()

    async def test_call_routes_still_require_a_workspace_session(self):
        app.dependency_overrides.pop(get_current_user)
        try:
            eligibility = await self.client.get(
                "/api/v1/calling-eligibility/auth-fixture",
                params={"phone_number": PHONE},
            )
            dispatch = await self.client.post(
                "/api/v1/calls/dispatch",
                json={
                    "lead_id": "auth-fixture",
                    "phone_number": PHONE,
                    "idempotency_key": str(uuid4()),
                    "confirmed": True,
                },
            )
        finally:
            app.dependency_overrides[get_current_user] = lambda: {
                "_id": "fixture-user",
                "email": "fixture@example.test",
            }
        self.assertEqual(eligibility.status_code, 401)
        self.assertEqual(dispatch.status_code, 401)
        self.evaluate.assert_not_called()
        self.dispatch.assert_not_called()

    async def test_consent_administration_still_requires_admin_bearer_token(self):
        path = "/api/v1/calling-eligibility/consent/auth-fixture"
        params = {"phone_number": PHONE}
        missing = await self.client.get(path, params=params)
        reviewer = await self.client.get(
            path, params=params, headers={"Authorization": "Bearer " + REVIEWER},
        )
        admin = await self.client.get(
            path, params=params, headers={"Authorization": "Bearer " + ADMIN},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(reviewer.status_code, 401)
        self.assertEqual(admin.status_code, 200)

    async def test_only_consent_administration_advertises_bearer_auth(self):
        schema = (await self.client.get("/openapi.json")).json()
        consent = schema["paths"]["/api/v1/calling-eligibility/consent/{lead_id}"]["get"]
        eligibility = schema["paths"]["/api/v1/calling-eligibility/{lead_id}"]["get"]
        dispatch = schema["paths"]["/api/v1/calls/dispatch"]["post"]
        self.assertEqual(consent["security"], [{"LeadSutraBearer": []}])
        self.assertNotIn("security", eligibility)
        self.assertNotIn("security", dispatch)


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
