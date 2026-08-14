from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import server


NOW = datetime.now(timezone.utc)
HOST = {"Host": "ai.motorinnautogroup.com"}


class AgentQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        server._page_cache.clear()
        server._catalog_cache.clear()
        server._inventory_cache.clear()
        with server._query_rate_lock:
            server._query_rate_limits.clear()
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def static_only(self):
        return (
            patch("server.render_inventory", side_effect=server.SourceUnavailable("inventory unavailable")),
            patch("server.rendered_offers", side_effect=server.SourceUnavailable("offers unavailable")),
        )

    def test_markdown_and_json_return_the_same_public_results(self) -> None:
        inventory_patch, offers_patch = self.static_only()
        with inventory_patch, offers_patch:
            json_response = self.client.get("/llms/json?query=service", headers=HOST)
            markdown_response = self.client.get("/llms/?query=service", headers=HOST)

        payload = json_response.get_json()
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(markdown_response.status_code, 200)
        self.assertTrue(markdown_response.content_type.startswith("text/markdown"))
        self.assertGreater(payload["resultCount"], 0)
        self.assertLessEqual(payload["resultCount"], 5)
        markdown = markdown_response.get_data(as_text=True)
        for result in payload["results"]:
            self.assertIn(f"`{result['id']}`", markdown)
            self.assertEqual(
                set(result),
                {"id", "title", "snippet", "canonicalUrl", "sourceUrl", "sourceType", "freshness"},
            )
            self.assertTrue(result["sourceUrl"].startswith("https://ai.motorinnautogroup.com/"))

    def test_default_is_five_results_and_limit_accepts_one_through_eight(self) -> None:
        documents = [
            server.QueryDocument(
                id=f"doc-{index}",
                title=f"Service document {index}",
                body="Service scheduling and maintenance",
                canonical_url=f"https://example.com/{index}",
                source_url=f"https://ai.example.com/{index}",
                source_type="static",
            )
            for index in range(8)
        ]
        with patch("server.build_query_documents", return_value=documents):
            default_response = self.client.get("/llms/json?query=service", headers=HOST)
            max_response = self.client.get("/llms/json?query=service&limit=8", headers=HOST)
            low_response = self.client.get("/llms/json?query=service&limit=0", headers=HOST)
            high_response = self.client.get("/llms/json?query=service&limit=9", headers=HOST)

        self.assertEqual(default_response.get_json()["resultCount"], 5)
        self.assertEqual(max_response.get_json()["resultCount"], 8)
        self.assertEqual(low_response.status_code, 400)
        self.assertEqual(high_response.status_code, 400)

    def test_query_validation_rejects_missing_empty_and_over_200_characters(self) -> None:
        self.assertEqual(self.client.get("/llms", headers=HOST).status_code, 400)
        self.assertEqual(self.client.get("/llms?query=%20%20", headers=HOST).status_code, 400)
        response = self.client.get("/llms/json", query_string={"query": "x" * 201}, headers=HOST)
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most 200", response.get_json()["error"])

    def test_private_inventory_fields_are_not_searchable_or_returned(self) -> None:
        public_rows = [
            {
                "id": "T1",
                "stock_number": "T1",
                "vin": "5TFJA5DB9TX443074",
                "condition": "new",
                "availability": "in stock",
                "vehicle_year": "2026",
                "vehicle_make": "TOYOTA",
                "vehicle_model": "Tundra",
                "vehicle_trim": "SR5",
                "link": "https://www.motorinnautogroup.com/new-tundra",
            }
        ]
        private_rows = [
            {
                "stock_number": "T1",
                "vin": "5TFJA5DB9TX443074",
                "internet_price": "50000",
                "customer_name": "PrivateCustomerToken",
                "cost": "PrivateCostToken",
                "appraisal_value": "PrivateAppraisalToken",
            }
        ]
        with (
            patch("server.load_catalog", return_value=(public_rows, NOW)),
            patch("server.load_private_inventory", return_value=(private_rows, NOW)),
            patch("server.rendered_offers", side_effect=server.SourceUnavailable("offers unavailable")),
        ):
            response = self.client.get("/llms/json?query=PrivateCustomerToken", headers=HOST)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["resultCount"], 0)
        self.assertNotIn("PrivateCustomerToken", body)
        self.assertNotIn("PrivateCostToken", body)
        self.assertNotIn("PrivateAppraisalToken", body)

    def test_nested_navigation_cleanup_keeps_public_offer_content(self) -> None:
        rendered = server.clean_html_to_markdown(
            "<html><body><nav><a href='/hidden'>Hidden</a></nav><main><h1>Summer offer</h1></main></body></html>",
            "https://www.motorinnautogroup.com",
        )
        self.assertIn("Summer offer", rendered)
        self.assertNotIn("Hidden", rendered)

    def test_telemetry_preserves_topics_and_redacts_pii(self) -> None:
        query = (
            "service Tundra my name is Jane Doe jane@example.com "
            "712-555-1212 5TFJA5DB9TX443074 account-123456789012"
        )
        inventory_patch, offers_patch = self.static_only()
        with inventory_patch, offers_patch, self.assertLogs("ai-markdown-proxy", level="INFO") as captured:
            response = self.client.get("/llms/json", query_string={"query": query}, headers=HOST)

        events = [json.loads(line.split(":", 2)[2]) for line in captured.output]
        telemetry = next(event for event in events if event.get("event") == "llms_query")
        sanitized = telemetry["sanitizedQuery"]
        self.assertEqual(response.status_code, 200)
        self.assertIn("service", sanitized)
        self.assertIn("Tundra", sanitized)
        for private_value in ("Jane", "Doe", "jane@example.com", "712-555-1212", "5TFJA5DB9TX443074", "account-123456789012"):
            self.assertNotIn(private_value, sanitized)
        self.assertIn("[redacted-name]", sanitized)
        self.assertIn("[redacted-email]", sanitized)
        self.assertIn("[redacted-phone]", sanitized)
        self.assertIn("[redacted-vin]", sanitized)
        self.assertIn("[redacted-id]", sanitized)
        self.assertEqual(telemetry["queryHash"], hashlib.sha256(sanitized.casefold().encode()).hexdigest())
        self.assertNotIn("remoteAddress", telemetry)
        self.assertEqual(
            {
                "event",
                "timestamp",
                "sanitizedQuery",
                "queryHash",
                "bot",
                "host",
                "resultCount",
                "topResultIds",
                "noResults",
                "latencyMs",
                "site",
            },
            set(telemetry),
        )

    def test_rate_limit_allows_60_per_ip_without_sleeping(self) -> None:
        documents = [
            server.QueryDocument(
                id="service",
                title="Service",
                body="Service scheduling",
                canonical_url="https://example.com/service",
                source_url="https://ai.example.com/service.md",
                source_type="static",
            )
        ]
        first_ip = {**HOST, "X-Forwarded-For": "203.0.113.10"}
        second_ip = {**HOST, "X-Forwarded-For": "203.0.113.11"}
        with patch("server.build_query_documents", return_value=documents), patch.object(server.logger, "info"):
            for _ in range(60):
                response = self.client.get("/llms/json?query=service&limit=1", headers=first_ip)
                self.assertEqual(response.status_code, 200)
            limited = self.client.get("/llms/json?query=service&limit=1", headers=first_ip)
            other_client = self.client.get("/llms/json?query=service&limit=1", headers=second_ip)

        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["Retry-After"], "60")
        self.assertEqual(other_client.status_code, 200)


if __name__ == "__main__":
    unittest.main()
