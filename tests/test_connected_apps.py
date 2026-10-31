from __future__ import annotations

import json
import struct
import unittest
from unittest.mock import patch

import server


HOST = {"Host": "ai.motorinnofcarroll.com"}
MCP_HEADERS = {
    "Host": "ai.motorinnofcarroll.com",
    "MCP-Protocol-Version": "2025-11-25",
}


class GoogleConnectedAppsTests(unittest.TestCase):
    def setUp(self) -> None:
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def test_default_mcp_includes_the_connected_app_tool_scope(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        tools = response.get_json()["result"]["tools"]
        names = [tool["name"] for tool in tools]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(names, [
            "search_vehicles",
            "get_vehicle",
            "list_locations",
            "get_service_information",
            "get_parts_information",
            "search_public_website",
            "submit_lead",
        ])
        self.assertLessEqual(max(len(tool["description"]) for tool in tools), 200)
        definitions = {tool["name"]: tool for tool in tools}
        self.assertTrue(definitions["get_vehicle"]["annotations"]["readOnlyHint"])
        self.assertFalse(definitions["submit_lead"]["annotations"]["readOnlyHint"])
        self.assertFalse(definitions["submit_lead"]["annotations"]["destructiveHint"])
        self.assertFalse(definitions["submit_lead"]["annotations"]["idempotentHint"])
        self.assertFalse(definitions["submit_lead"]["inputSchema"]["additionalProperties"])

    def test_mcp_initialize_has_reviewable_server_instructions(self) -> None:
        initialize = self.client.post("/mcp", headers=MCP_HEADERS, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        })
        result = initialize.get_json()["result"]

        self.assertEqual(initialize.status_code, 200)
        instructions = result["serverInstructions"]
        self.assertIn("search_vehicles", instructions)
        self.assertIn("get_vehicle", instructions)
        self.assertIn("get_service_information", instructions)
        self.assertIn("get_parts_information", instructions)
        self.assertIn("search_public_website", instructions)
        self.assertIn("submit_lead", instructions)
        self.assertIn("not idempotent", instructions)
        self.assertIn("Do not claim vehicle reservations", instructions)

    def test_google_verification_certificate_route(self) -> None:
        env = {
            "GOOGLE_SITE_VERIFICATION": json.dumps({
                "ai.motorinnofcarroll.com": "test-carroll-token",
                "ai.motorinntoyotaofcarroll.com": "test-toyota-token",
            }),
        }
        with patch.dict("server.os.environ", env, clear=False):
            certificate = self.client.get("/.well-known/google-connected-apps", headers=HOST)
            friendly = self.client.get("/google-verification/test-carroll-token", headers=HOST)
            other = self.client.get("/google-verification/test-toyota-token", headers=HOST)

        self.assertEqual(certificate.status_code, 200)
        self.assertEqual(certificate.get_json(), {"verification_tokens": ["test-carroll-token"]})
        self.assertEqual(friendly.status_code, 200)
        self.assertEqual(friendly.content_type, "text/plain; charset=utf-8")
        self.assertEqual(friendly.get_data(as_text=True), "test-carroll-token")
        self.assertEqual(other.status_code, 404)

    def test_terms_privacy_and_icon_routes_are_site_scoped(self) -> None:
        terms = self.client.get("/terms", headers=HOST)
        privacy = self.client.get("/privacy", headers=HOST)
        icon = self.client.get("/assets/icon-512.png", headers=HOST)

        self.assertEqual(terms.status_code, 200)
        self.assertEqual(privacy.status_code, 200)
        self.assertEqual(icon.status_code, 200)
        self.assertTrue(terms.content_type.startswith("text/html"))
        self.assertTrue(privacy.content_type.startswith("text/html"))
        self.assertTrue(icon.content_type.startswith("image/png"))
        self.assertIn("Motor Inn", terms.get_data(as_text=True))
        self.assertIn("https://www.motorinnofcarroll.com/privacy.aspx", privacy.get_data(as_text=True))
        payload = icon.get_data()
        self.assertGreater(len(payload), 4000)
        self.assertEqual(struct.unpack(">II", payload[16:24]), (512, 512))

    def test_every_site_has_an_icon_asset(self) -> None:
        for site_key in server.SITES:
            path = server.ASSETS_ROOT / site_key / "icon-512.png"
            self.assertTrue(path.is_file(), f"missing icon for {site_key}")

    def test_listing_metadata_has_each_store(self) -> None:
        body = server.Path("docs/connected-app-listing.md").read_text()
        self.assertIn("Motor Inn of Carroll", body)
        self.assertIn("Motor Inn Toyota of Carroll", body)
        self.assertIn("Motor Inn Auto Group", body)
        self.assertIn("Automotive", body)
        self.assertIn("@Motor Inn", body)
        self.assertIn("/terms", body)
        self.assertIn("/privacy", body)
        self.assertIn("/assets/icon-512.png", body)


if __name__ == "__main__":
    unittest.main()
