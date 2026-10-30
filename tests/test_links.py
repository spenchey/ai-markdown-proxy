from __future__ import annotations

import csv
import html
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from pathlib import Path
from bs4 import BeautifulSoup

import server


class LinkTests(unittest.TestCase):
    def setUp(self) -> None:
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def test_all_audited_link_records_are_loaded(self) -> None:
        self.assertEqual(len(server.link_records()), 200)

    def test_each_host_serves_a_plain_links_index(self) -> None:
        for site in server.SITES.values():
            with self.subTest(site=site.key):
                response = self.client.get(f"/links/{site.key}.html", headers={"Host": site.ai_host})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content_type.startswith("text/html"))
                self.assertIn(response.headers["Cache-Control"], "public, max-age=3600")
                self.assertEqual(response.headers["X-Robots-Tag"], "noindex, follow")
                soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
                self.assertIn("Top 20", soup.get_text())
                links = soup.select("#related-pages a")
                self.assertEqual(len(links), len(server.link_records_for_site(site)))
                self.assertTrue(all(link.get("rel") == ["internal", "follow"] for link in links))
                self.assertTrue(all(link.get_text().strip() for link in links))

    def test_index_keeps_top20_before_the_remainder(self) -> None:
        for site in server.SITES.values():
            with self.subTest(site=site.key):
                records = server.link_records_for_site(site)
                self.assertGreaterEqual(len(records), 20)
                page = server.related_links_page(site)
                soup = BeautifulSoup(page, "html.parser")
                headings = [element.get_text(strip=True) for element in soup.find_all("h2")]
                self.assertEqual(headings.index("Top 20"), 0)
                self.assertLess(headings.index("Top 20"), headings.index("All supporting links"))

    def test_injected_block_uses_exact_anchor_text(self) -> None:
        site = server.SITES["motorinnautogroup"]
        records = [record for record in server.link_records_for_site(site) if urlsplit(record.source_url).path == "/"]
        self.assertTrue(records)
        page = server.inject_related_links(
            "<html><body><main>Root page</main></body></html>",
            site,
            "/",
        )
        soup = BeautifulSoup(page, "html.parser")
        injected = soup.select("#related-pages a")
        self.assertEqual([link.get_text() for link in injected], [record.anchor_text for record in records])
        self.assertTrue(all(link.get("rel") == ["internal", "follow"] for link in injected))

    def test_cross_domain_links_stay_absolute_and_same_host_links_are_relative(self) -> None:
        site = server.SITES["motorinnautogroup"]
        records = server.link_records_for_site(site)
        cross_domain = next(record for record in records if urlsplit(record.source_url).hostname != urlsplit(record.dest_url).hostname)
        same_host = next(record for record in records if urlsplit(record.source_url).hostname == urlsplit(record.dest_url).hostname)
        self.assertEqual(server.mirror_href(site, cross_domain.dest_url), cross_domain.dest_url)
        self.assertEqual(server.mirror_href(site, same_host.dest_url), urlsplit(same_host.dest_url).path)

    def test_hub_page_uses_explore_label(self) -> None:
        site = server.SITES["motorinnautogroup"]
        page = server.inject_related_links(
            "<html><body><main>Root page</main></body></html>",
            site,
            "/",
        )
        soup = BeautifulSoup(page, "html.parser")
        self.assertEqual(soup.select_one("#related-pages h2").get_text(), "Explore")


if __name__ == "__main__":
    unittest.main()
