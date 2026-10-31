from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

import server


SLUG = "used-trucks-towing-iowa"
ARTICLE_PATH = f"/articles/{SLUG}"
HOSTS = (
    ("ai.motorinnautogroup.com", "motorinnautogroup"),
    ("ai.motorinntoyotaofcarroll.com", "motorinntoyota"),
    ("ai.motorinnofcarroll.com", "motorinnchevy"),
)


class ArticleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_article_route_serves_host_canonical_schema_and_links(self) -> None:
        for host, site_key in HOSTS:
            response = self.client.get(ARTICLE_PATH, headers={"Host": host})
            self.assertEqual(response.status_code, 200, host)
            self.assertTrue(response.content_type.startswith("text/html"), host)
            self.assertEqual(response.headers.get("X-Robots-Tag"), "index, follow", host)
            soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
            self.assertEqual(soup.title.get_text(strip=True), "Used Trucks for Towing in Iowa: How to Pick a Truck You Can Trust", host)
            self.assertEqual(soup.find("link", rel="canonical")["href"], f"https://{host}/articles/{SLUG}", host)
            hrefs = {anchor["href"] for anchor in soup.find_all("a")}
            links_site = server.SITES[server.HOST_TO_SITE[host]]
            self.assertIn(f"/links/{links_site.key}.html", hrefs, hrefs)
            self.assertIn("/used-inventory.md", hrefs)
            expected_contact = (
                "https://www.motorinnofcarroll.com/contactus.aspx"
                if site_key == "motorinnchevy"
                else f"https://www.{'motorinntoyotaofcarroll' if site_key == 'motorinntoyota' else 'motorinnautogroup'}.com/contactus.html"
            )
            self.assertIn(expected_contact, hrefs, hrefs)
            self.assertIn("https://www.chevrolet.com/trucks/silverado/1500", hrefs)

    def test_article_is_in_sitemap_llms_ai_catalog_and_links_index(self) -> None:
        for host, site_key in HOSTS:
            article_url = f"https://{host}/articles/{SLUG}"
            sitemap = self.client.get("/sitemap.xml", headers={"Host": host}).get_data(as_text=True)
            self.assertIn(article_url, sitemap)
            llms = self.client.get("/llms.txt", headers={"Host": host}).get_data(as_text=True)
            self.assertIn(article_url, llms)
            self.assertIn("## Guides", llms)
            ai_catalog = self.client.get("/ai.txt", headers={"Host": host}).get_data(as_text=True)
            self.assertIn(article_url, ai_catalog)
            links_slug = {"motorinnautogroup": "motorinnautogroup", "motorinntoyota": "motorinntoyotaofcarroll", "motorinnchevy": "motorinnofcarroll"}[site_key]
            links_page = self.client.get(f"/links/{links_slug}.html", headers={"Host": host}).get_data(as_text=True)
            self.assertIn(article_url, links_page)


if __name__ == "__main__":
    unittest.main()
