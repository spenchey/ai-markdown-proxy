from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import server
from vehicle_pages import find_row, load_answer_pages, normalize_vin, render_vehicle_markdown

NOW = datetime.now(timezone.utc)
HOST = {"Host": "ai.motorinnautogroup.com"}

ROW = {
    "vin": "3GNAXPEG1SL228732",
    "condition": "used",
    "vehicle_year": "2025",
    "vehicle_make": "CHEVROLET",
    "vehicle_model": "Equinox",
    "vehicle_trim": "LT",
    "availability": "in stock",
    "display_price": 26051,
    "dealerVault": {
        "odometer": 36463,
        "vehicle_body": "Sport Utility",
        "exterior_color": "Silver",
        "engine_desc": "1.5L Turbo",
        "link": "/used-Carroll-2025-Chevrolet-Equinox-AWD+LT-3GNAXPEG1SL228732",
    },
}


def rows() -> tuple[list[dict], datetime, datetime]:
    return [ROW], NOW, NOW


class VehiclePageUnitTests(unittest.TestCase):
    def test_render_includes_facts(self) -> None:
        body = render_vehicle_markdown(dict(ROW, canonical_link="https://x/v"), "fee note", "Motor Inn")
        for token in ("3GNAXPEG1SL228732", "$26,051", "36,463 miles", "Sport Utility", "Canonical vehicle page"):
            self.assertIn(token, body)

    def test_find_row_case_insensitive(self) -> None:
        self.assertIsNotNone(find_row([ROW], "3gnaxpeg1sl228732"))
        self.assertIsNone(find_row([], "3GNAXPEG1SL228732"))

    def test_normalize_vin_strips(self) -> None:
        self.assertEqual(normalize_vin(" 3gn-axpeg1sl228732 "), "3GNAXPEG1SL228732")


class VehiclePageRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        server._page_cache.clear()
        server._catalog_cache.clear()
        server._inventory_cache.clear()
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def test_md_route_serves_markdown(self) -> None:
        with patch("server.match_rows", side_effect=rows):
            response = self.client.get("/v/3GNAXPEG1SL228732.md", headers=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/markdown"))
        self.assertIn("3GNAXPEG1SL228732", response.get_data(as_text=True))

    def test_html_route_serves_html(self) -> None:
        with patch("server.match_rows", side_effect=rows):
            response = self.client.get("/v/3GNAXPEG1SL228732.html", headers=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<html", response.data)

    def test_unknown_vin_404(self) -> None:
        with patch("server.match_rows", side_effect=rows):
            response = self.client.get("/v/1AAAAAA11A1AA11111", headers=HOST)
        self.assertEqual(response.status_code, 404)

    def test_short_vin_rejected(self) -> None:
        response = self.client.get("/v/ABC", headers=HOST)
        self.assertEqual(response.status_code, 404)

    def test_answer_page_serves(self) -> None:
        response = self.client.get("/answers/bad-credit-car-financing-carroll.md", headers=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bad Credit", response.get_data(as_text=True))

    def test_answer_index_lists_pages(self) -> None:
        response = self.client.get("/answers", headers=HOST)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("/answers/bad-credit-car-financing-carroll.md", body)

    def test_answer_unknown_slug_404(self) -> None:
        response = self.client.get("/answers/nope.md", headers=HOST)
        self.assertEqual(response.status_code, 404)

    def test_sitemap_includes_answers(self) -> None:
        with patch("server.match_rows", side_effect=rows):
            response = self.client.get("/sitemap.xml", headers=HOST)
        self.assertIn(b"/answers/bad-credit-car-financing-carroll", response.data)


class AnswerPageDataTests(unittest.TestCase):
    def test_all_pages_have_meta_and_body(self) -> None:
        pages, _gen = load_answer_pages()
        self.assertGreaterEqual(len(pages), 4)
        for page in pages:
            self.assertTrue(page.slug)
            self.assertTrue(page.title)
            self.assertTrue(page.body.strip())
            self.assertIn("motorinnautogroup", page.dealer_keys)


if __name__ == "__main__":
    unittest.main()
