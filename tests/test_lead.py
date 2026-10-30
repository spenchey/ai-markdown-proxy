from __future__ import annotations

import unittest
from unittest.mock import patch

import server


class LeadRouteTests(unittest.TestCase):
    def test_lead_upstream_token(self) -> None:
        with patch("server.requests.get") as get:
            get.return_value.raise_for_status.return_value = None
            get.return_value.json.return_value = {"token": "test-token"}
            self.assertEqual(server.lead_upstream_token("www.motorinnofcarroll.com"), "test-token")
            get.assert_called_once_with("https://www.motorinnofcarroll.com/api/lead/new", timeout=20)

    def test_lead_upstream_payload(self) -> None:
        payload = server.lead_upstream_payload(
            {
                "name": "Jeeves Mirror Test",
                "email": "jeeves+leadtest@motorinnmail.com",
                "phone": "7125550142",
                "message": "E2E lead-path test - safe to discard",
                "source": "ai.motorinnofcarroll.com",
            }
        )
        self.assertEqual(payload["FirstName"], "Jeeves")
        self.assertEqual(payload["LastName"], "Mirror Test")
        self.assertEqual(payload["Email"], "jeeves+leadtest@motorinnmail.com")
        self.assertEqual(payload["Phone"], "7125550142")
        self.assertEqual(payload["LeadSource"], 32)
        self.assertEqual(payload["LeadType"], "9")
        self.assertIn("AI Agent", payload["Comments"])

    def test_rate_limit(self) -> None:
        self.assertTrue(server.lead_rate_limit_allowed("test", now=100.0))
        for _ in range(9):
            self.assertTrue(server.lead_rate_limit_allowed("test", now=101.0))
        self.assertFalse(server.lead_rate_limit_allowed("test", now=102.0))
        self.assertTrue(server.lead_rate_limit_allowed("other", now=102.0))

    def test_lead_route_registered(self) -> None:
        assert hasattr(server, "serve_lead")
        client = server.app.test_client()
        response = client.post(
            "/lead",
            json={},
            headers={"X-Forwarded-For": "192.0.2.1"},
        )
        self.assertEqual(response.status_code, 400)
