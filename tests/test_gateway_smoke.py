import os
import tempfile
import unittest
from pathlib import Path


class GatewaySmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        os.environ["GATEWAY_DATABASE_URL"] = f"sqlite:///{(root / 'test.db').as_posix()}"
        os.environ["GATEWAY_STORAGE_ROOT"] = str(root / "storage")
        os.environ["GATEWAY_PROFILES_ROOT"] = str(root / "storage" / "profiles")
        os.environ["GATEWAY_ADMIN_USERNAME"] = "admin"
        os.environ["GATEWAY_ADMIN_PASSWORD"] = "secret123"
        os.environ["GATEWAY_ADMIN_TOKEN_SECRET"] = "test-secret"

        from fastapi.testclient import TestClient

        from app.main import app

        cls.client = TestClient(app)
        cls.client.__enter__()
        login = cls.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        cls.admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        from app.db.session import engine

        engine.dispose()
        cls.temp_dir.cleanup()

    def test_health_meta_and_overview(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        bootstrap = self.client.get("/api/auth/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()["username"], "admin")

        meta = self.client.get("/api/meta", headers=self.admin_headers)
        self.assertEqual(meta.status_code, 200)
        body = meta.json()
        self.assertIn("grok", body["categories"])
        self.assertIn("flow", body["categories"])
        self.assertIn("dreamina", body["categories"])

        overview = self.client.get("/api/overview", headers=self.admin_headers)
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.json()["profiles"]["total"], 0)

    def test_profile_and_api_key_crud_entrypoints(self):
        profile_payload = {
            "name": "smoke-grok",
            "category": "grok",
            "description": "smoke profile",
            "tags": ["smoke"],
            "concurrency_limit": 1,
            "antidetect": {
                "locale": "en-US",
                "timezone_id": "UTC",
                "viewport_width": 1280,
                "viewport_height": 720,
                "platform": "Win32",
                "hardware_concurrency": 8,
            },
        }
        profile = self.client.post("/api/profiles", json=profile_payload, headers=self.admin_headers)
        self.assertEqual(profile.status_code, 201)
        profile_body = profile.json()
        self.assertEqual(profile_body["category"], "grok")
        self.assertTrue(Path(profile_body["cache_dir"]).exists())

        api_key = self.client.post(
            "/api/api-keys",
            json={
                "name": "smoke-client",
                "rate_limit_per_minute": 5,
                "allowed_categories": ["grok"],
            },
            headers=self.admin_headers,
        )
        self.assertEqual(api_key.status_code, 201)
        api_key_body = api_key.json()
        self.assertTrue(api_key_body["plain_key"].startswith("gg_"))

        blocked_job = self.client.post(
            "/api/jobs",
            json={
                "profile_id": profile_body["id"],
                "target": "image",
                "prompt": "test",
                "count": 1,
                "provider_payload": {},
            },
            headers=self.admin_headers,
        )
        self.assertEqual(blocked_job.status_code, 409)


if __name__ == "__main__":
    unittest.main()
