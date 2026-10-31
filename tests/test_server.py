from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import server


NOW = datetime.now(timezone.utc)


class ProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        server._page_cache.clear()
        server._catalog_cache.clear()
        server._inventory_cache.clear()
        with server._query_rate_lock:
            server._query_rate_limits.clear()
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()
        self._links_patches = [
            patch.object(server, "related_link_records", return_value=()),
            patch.object(server, "source_is_hub", return_value=False),
        ]
        for patcher in self._links_patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._links_patches:
            patcher.stop()
        self._links_patches = [
            patch.object(server, "related_link_records", return_value=()),
            patch.object(server, "source_is_hub", return_value=False),
        ]
        for patcher in self._links_patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._links_patches:
            patcher.stop()
        self._links_patches: list[unittest.mock.patch] = []

    def patch_links(self) -> None:
        """Remove injected link behavior when testing independent proxy surfaces."""
        self._links_patches.append(
            patch.object(server, "related_link_records", side_effect=lambda site, path: ())
        )
        self._links_patches.append(
            patch.object(server, "source_is_hub", side_effect=lambda site, path: False)
        )
        for patcher in self._links_patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._links_patches:
            patcher.stop()
        self._links_patches.clear()

    def test_host_selects_site_specific_validated_content(self) -> None:
        response = self.client.get("/llms.txt", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/markdown"))
        self.assertIn("# Motor Inn of Carroll", response.get_data(as_text=True))
        self.assertIn("https://ai.motorinnofcarroll.com/dealership.md", response.get_data(as_text=True))
        self.assertIn("https://ai.motorinnofcarroll.com/llms?query=service&limit=3", response.get_data(as_text=True))
        self.assertNotIn("https://www.motorinnofcarroll.com/dealership.md", response.get_data(as_text=True))

    def test_inventory_table_is_host_scoped_and_cached_daily(self) -> None:
        public = [
            {
                "id": "C1",
                "stock_number": "C1",
                "vin": "VIN1-CHEVY-ROOFTOP",
                "condition": "new",
                "availability": "in stock",
                "vehicle_year": "2024",
                "vehicle_make": "CHEVROLET",
                "vehicle_model": "Malibu",
                "vehicle_trim": "LT",
                "link": "https://www.motorinnofcarroll.com/vehicle/C1",
                "image_link": "https://images.example/C1.jpg",
            }
        ]
        private = [{"stock_number": "C1", "vin": "VIN1-CHEVY-ROOFTOP", "internet_price": "25000", "odometer": "10,000"}]
        with patch("server.load_catalog", return_value=(public, NOW)), patch("server.load_private_inventory", return_value=(private, NOW)):
            first = self.client.get("/inventory.md", headers={"Host": "ai.motorinnofcarroll.com"})
            second = self.client.get("/inventory.md", headers={"Host": "ai.motorinnofcarroll.com"})
        body = first.get_data(as_text=True)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.content_type.startswith("text/markdown"))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_data(), second.get_data())
        self.assertIn("DealerVault last updated", body)
        self.assertIn("Public catalog last updated", body)
        self.assertIn("| VIN | Year | Make | Model | Trim | Price | Miles | Body | Photo | Dealer comments |", body)
        self.assertIn("| VIN1-CHEVY-ROOFTOP | 2024 | CHEVROLET | Malibu | LT | $25,180 | 10,000 ", body)
        self.assertIn("| [photo](https://images.example/C1.jpg) |", body)
        self.assertIn("public, max-age=86400", first.headers["Cache-Control"])

    def test_inventory_table_is_limited_to_matching_rooftop(self) -> None:
        public = [
            {
                "id": "TOY1",
                "stock_number": "TOY1",
                "vin": "VIN2-TOYOTA-ROOFTO",
                "condition": "new",
                "availability": "in stock",
                "vehicle_year": "2024",
                "vehicle_make": "TOYOTA",
                "vehicle_model": "Tundra",
                "vehicle_trim": "SR5",
                "link": "https://www.motorinntoyotaofcarroll.com/vehicle/TOY1",
                "image_link": "",
            }
        ]
        private = [{"stock_number": "TOY1", "vin": "VIN2-TOYOTA-ROOFTO", "internet_price": "50000"}]
        with patch("server.load_catalog", return_value=(public, NOW)), patch("server.load_private_inventory", return_value=(private, NOW)):
            response = self.client.get("/inventory.md", headers={"Host": "ai.motorinntoyotaofcarroll.com"})
        body = response.get_data(as_text=True)
        self.assertIn("VIN2-TOYOTA-ROOFTO", body)
        self.assertNotIn("VIN1-CHEVY-ROOFTOP", body)

    def test_inventory_table_fails_closed_when_source_is_unavailable(self) -> None:
        with patch("server.load_catalog", side_effect=server.SourceUnavailable("catalog stale")):
            response = self.client.get("/inventory.md", headers={"Host": "ai.motorinnautogroup.com"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("catalog stale", response.get_data(as_text=True))

    def test_sitemap_and_llms_txt_expose_inventory_table(self) -> None:
        sitemap = self.client.get("/sitemap.xml", headers={"Host": "ai.motorinnofcarroll.com"}).get_data(as_text=True)
        llms = self.client.get("/llms.txt", headers={"Host": "ai.motorinnofcarroll.com"}).get_data(as_text=True)
        self.assertIn("https://ai.motorinnofcarroll.com/inventory.md", sitemap)
        self.assertIn("/inventory.md", llms)


    def test_feed_json_lists_validated_site_pages(self) -> None:
        response = self.client.get("/feed.json", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("application/json"))
        items = response.get_json()
        self.assertTrue(items)
        self.assertEqual({k for k in items[0]}, {"site", "url", "title", "updated", "summary"})
        self.assertTrue(all(item["site"] == "motorinnchevy" for item in items))
        self.assertIn("public", response.headers["Cache-Control"])

    def test_llms_txt_exposes_machine_readable_feed_pointer(self) -> None:
        response = self.client.get("/llms.txt", headers={"Host": "ai.motorinnautogroup.com"})
        self.assertIn("# machine-readable: /feed.json", response.get_data(as_text=True))


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

    def test_gbp_review_operations_page_is_limited_to_motor_inn_auto_group(self) -> None:
        response = self.client.get("/gbp-review-operations", headers={"Host": "ai.motorinnautogroup.com"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/html"))
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, follow")
        self.assertIn("Motor Inn Auto Group GBP Review Operations", body)
        self.assertIn("official home page", body)
        self.assertIn("Google Business Profile feedback", body)
        self.assertIn("approval-gated", body)
        self.assertIn("https://www.motorinnautogroup.com/privacy-policy", body)
        self.assertIn("https://www.motorinnautogroup.com/terms", body)

        other_site = self.client.get("/gbp-review-operations", headers={"Host": "ai.motorinnofcarroll.com"})
        self.assertEqual(other_site.status_code, 404)
