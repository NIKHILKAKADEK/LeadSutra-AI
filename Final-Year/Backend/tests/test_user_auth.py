from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from app.app import app


class FakeUsers:
    def __init__(self):
        self.documents: dict[str, dict] = {}

    def find_one(self, query, projection=None):
        for document in self.documents.values():
            if all(document.get(key) == value for key, value in query.items()):
                return document.copy()
        return None

    def insert_one(self, document):
        self.documents[document["_id"]] = document.copy()


class UserAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.users = FakeUsers()
        self.settings = SimpleNamespace(
            auth_jwt_secret=SecretStr("a-test-only-signing-secret-with-more-than-32-characters"),
            auth_cookie_name="test_session",
            auth_cookie_secure=False,
        )
        self.stack = unittest.mock.patch(
            "app.auth.get_settings", return_value=self.settings,
        )
        self.stack.start()
        self.addAsyncCleanup(self.stack.stop)
        collection_patch = patch(
            "app.auth.get_mongo_collection",
            side_effect=lambda name: self.users if name == "users" else None,
        )
        collection_patch.start()
        self.addAsyncCleanup(collection_patch.stop)
        self.api_settings_patch = patch(
            "app.api.v1.auth.get_settings", return_value=self.settings,
        )
        self.api_settings_patch.start()
        self.addAsyncCleanup(self.api_settings_patch.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_signup_hashes_password_and_sets_http_only_session_cookie(self):
        response = await self.client.post(
            "/api/v1/auth/signup",
            json={"name": "Test User", "email": "TEST@example.com", "password": "long-test-password"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user"]["email"], "test@example.com")
        self.assertNotIn("password", response.text)
        stored = next(iter(self.users.documents.values()))
        self.assertNotEqual(stored["password_hash"], "long-test-password")
        self.assertIn("$argon2", stored["password_hash"])
        cookie = response.headers["set-cookie"].casefold()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)

    async def test_login_verifies_password_and_rejects_invalid_credentials(self):
        await self.client.post(
            "/api/v1/auth/signup",
            json={"name": "Test User", "email": "user@example.com", "password": "long-test-password"},
        )
        accepted = await self.client.post(
            "/api/v1/auth/login",
            json={"email": "USER@example.com", "password": "long-test-password"},
        )
        rejected = await self.client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "incorrect-password"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("test_session=", accepted.headers["set-cookie"])
        self.assertEqual(rejected.status_code, 401)

    async def test_session_restoration_and_protected_api_route(self):
        missing_session = await self.client.post(
            "/api/v1/leads/discover",
            json={"query": "gym", "location": "Nashik", "limit": 1},
        )
        self.assertEqual(missing_session.status_code, 401)

        await self.client.post(
            "/api/v1/auth/signup",
            json={"name": "Test User", "email": "user@example.com", "password": "long-test-password"},
        )
        current = await self.client.get("/api/v1/auth/me")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["user"]["name"], "Test User")

    async def test_signup_rejects_duplicate_email(self):
        payload = {"name": "Test User", "email": "user@example.com", "password": "long-test-password"}
        first = await self.client.post("/api/v1/auth/signup", json=payload)
        second = await self.client.post(
            "/api/v1/auth/signup",
            json={**payload, "email": "USER@example.com"},
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
