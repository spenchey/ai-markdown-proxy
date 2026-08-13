from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import server


NOW = datetime.now(timezone.utc)


class ProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        server._page_cache.clear()
        server._catalog_cache.clear()
        server._inventory_cache.clear()
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def test_host_selects_site_specific_validated_content(self) -> None:
        response = self.client.get("/llms.txt", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/markdown"))
        self.assertIn("# Motor Inn of Carroll", response.get_data(as_text=True))
        self.assertIn("https://ai.motorinnofcarroll.com/dealership.md", response.get_data(as_text=True))
        self.assertNotIn("https://www.motorinnofcarroll.com/dealership.md", response.get_data(as_text=True))

    def test_cached_markdown_keeps_markdown_content_type_and_vary(self) -> None:
        with patch("server.fetch_page", return_value="<html><body><main><h1>Test</h1></main></body></html>"):
            first = self.client.get("/aboutus.aspx", headers={"Host": "ai.motorinnautogroup.com", "Accept": "text/markdown"})
            second = self.client.get("/aboutus.aspx", headers={"Host": "ai.motorinnautogroup.com", "Accept": "text/markdown"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.content_type.startswith("text/markdown"))
        self.assertEqual(second.headers["Vary"], "Accept")

    def test_html_request_redirects_to_canonical_dealeron_page(self) -> None:
        response = self.client.get("/aboutus.aspx", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://www.motorinnofcarroll.com/aboutus.aspx")

    def test_root_html_is_an_independent_discovery_index(self) -> None:
        response = self.client.get("/", headers={"Host": "ai.motorinnofcarroll.com"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/html"))
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, follow")
        self.assertIn('<link rel="canonical" href="https://www.motorinnofcarroll.com">', body)
        self.assertIn('href="/llms.txt"', body)
        self.assertIn('href="/sitemap.xml"', body)
        self.assertNotIn("motorinntoyotaofcarroll.com", body)

    def test_sitemap_lists_only_matching_ai_host_resources(self) -> None:
        response = self.client.get("/sitemap.xml", headers={"Host": "ai.motorinnofcarroll.com"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("application/xml"))
        self.assertIn("https://ai.motorinnofcarroll.com/llms.txt", body)
        self.assertIn("https://ai.motorinnofcarroll.com/new-inventory.md", body)
        self.assertNotIn("www.motorinnofcarroll.com", body)
        self.assertNotIn("ai.motorinntoyotaofcarroll.com", body)

    def test_inventory_is_dealervault_gated_and_price_includes_doc_fee(self) -> None:
        public = [
            {
                "id": "T1",
                "stock_number": "T1",
                "vin": "VIN1",
                "condition": "new",
                "availability": "in stock",
                "vehicle_year": "2026",
                "vehicle_make": "TOYOTA",
                "vehicle_model": "Tundra",
                "vehicle_trim": "SR5",
                "link": "https://www.motorinnautogroup.com/new-tundra?utm_source=meta",
                "image_link": "https://example.com/tundra.png",
            },
            {
                "id": "STALE",
                "stock_number": "STALE",
                "vin": "VIN2",
                "condition": "new",
                "vehicle_year": "2026",
                "vehicle_make": "TOYOTA",
                "vehicle_model": "Stale",
                "link": "https://example.com/stale",
            },
        ]
        private = [{"stock_number": "T1", "vin": "VIN1", "internet_price": "50000", "odometer": "0"}]
        with patch("server.load_catalog", return_value=(public, NOW)), patch("server.load_private_inventory", return_value=(private, NOW)):
            response = self.client.get("/new-inventory.md", headers={"Host": "ai.motorinntoyotaofcarroll.com"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("$50,180", body)
        self.assertIn("including $180 documentation fee", body)
        self.assertIn("Plus tax, title, and license", body)
        self.assertIn("https://www.motorinnautogroup.com/new-tundra", body)
        self.assertNotIn("utm_source", body)
        self.assertNotIn("Stale", body)

    def test_inventory_fails_closed_when_source_is_unavailable(self) -> None:
        with patch("server.load_catalog", side_effect=server.SourceUnavailable("catalog stale")):
            response = self.client.get("/new-inventory.md", headers={"Host": "ai.motorinnautogroup.com"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("catalog stale", response.get_data(as_text=True))

    def test_search_crawlers_allowed_and_training_crawlers_blocked(self) -> None:
        response = self.client.get("/robots.txt", headers={"Host": "ai.motorinnautogroup.com"})
        body = response.get_data(as_text=True)
        self.assertIn("User-agent: OAI-SearchBot\nAllow: /", body)
        self.assertIn("User-agent: GPTBot\nDisallow: /", body)
        self.assertIn("Sitemap: https://ai.motorinnautogroup.com/sitemap.xml", body)
        self.assertNotIn("Sitemap: https://www.motorinnautogroup.com", body)

    def test_full_health_reports_matched_source_state(self) -> None:
        with patch("server.match_rows", return_value=([{"stock_number": "T1"}], NOW, NOW)):
            response = self.client.get("/__health/full")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["matchedInventory"], 1)


if __name__ == "__main__":
    unittest.main()
