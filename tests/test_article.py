"""Table-driven LEG A coverage: all 7 articles x allowed/disallowed hosts x chrome x links
x sitemap x llms x ai.txt x links index x feed x query search."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

import server


HOSTS = (
    ("ai.motorinnautogroup.com", "motorinnautogroup"),
    ("ai.motorinntoyotaofcarroll.com", "motorinntoyota"),
    ("ai.motorinnofcarroll.com", "motorinnchevy"),
)

# Distinctive query tokens that only occur in that article's body.
QUERY_TOKENS = {
    "used-trucks-towing-iowa": "trailer brake controller",
    "aboutus-augment-spirit-lake": "Spirit Lake",
    "heavy-duty-vs-light-duty-trucks": " GVWR ",
    "highlander-vs-grand-highlander": "Grand Highlander",
    "toyota-rav4-carroll-iowa": "RAV4",
    "trim-levels-explained": "trim level",
    "used-car-maintenance-mileage": "maintenance",
}

FORBIDDEN_CHROME_MARKERS = ("dealerOnTrack", "typekit", "cdn.dealershipinc")


def expected_contact(site_key: str) -> str:
    if site_key == "motorinnchevy":
        return "https://www.motorinnofcarroll.com/contactus.aspx"
    host = "motorinntoyotaofcarroll" if site_key == "motorinntoyota" else "motorinnautogroup"
    return f"https://www.{host}.com/contactus.html"


class ArticleHostMembershipTests(unittest.TestCase):
    """Every catalog article: allowed hosts serve it, disallowed hosts 404 it."""

    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_all_articles_serve_on_allowed_hosts_and_404_elsewhere(self) -> None:
        for record in server.article_catalog():
            slug = record["slug"]
            for host, site_key in HOSTS:
                allowed = site_key in record["sites"]
                response = self.client.get(f"/articles/{slug}", headers={"Host": host})
                if allowed:
                    self.assertEqual(response.status_code, 200, (slug, host))
                else:
                    self.assertEqual(response.status_code, 404, (slug, host))

    def test_page_head_title_canonical_and_schema(self) -> None:
        for record in server.article_catalog():
            slug = record["slug"]
            for host, site_key in HOSTS:
                if site_key not in record["sites"]:
                    continue
                soup = BeautifulSoup(
                    self.client.get(f"/articles/{slug}", headers={"Host": host}).get_data(as_text=True),
                    "html.parser",
                )
                self.assertEqual(soup.title.get_text(strip=True), record["title"], (slug, host))
                self.assertEqual(
                    soup.find("link", rel="canonical")["href"],
                    f"https://{host}/articles/{slug}",
                    (slug, host),
                )
                schemas = soup.find_all("script", type="application/ld+json")
                self.assertTrue(any("Article" in (s.string or "") for s in schemas), (slug, host))
                if slug != "used-trucks-towing-iowa":
                    # wave-2 fragments retain their validated FAQPage JSON-LD
                    self.assertTrue(any("FAQPage" in (s.string or "") for s in schemas), (slug, host))

    def test_house_hero_and_question_h2s_no_chrome(self) -> None:
        for record in server.article_catalog():
            slug = record["slug"]
            host = next(h for h, key in HOSTS if key in record["sites"])
            html = self.client.get(f"/articles/{slug}", headers={"Host": host}).get_data(as_text=True)
            soup = BeautifulSoup(html, "html.parser")
            hero = soup.find("aside", class_="hero")
            self.assertIsNotNone(hero, slug)
            self.assertIsNotNone(hero.find("h1"), slug)
            self.assertTrue(hero.get_text(strip=True), slug)
            self.assertGreaterEqual(len(soup.find_all("h2")), 3, slug)
            for marker in FORBIDDEN_CHROME_MARKERS:
                self.assertNotIn(marker, html, (slug, marker))

    def test_links_absolute_live_www_and_host_aware_contact(self) -> None:
        for record in server.article_catalog():
            slug = record["slug"]
            for host, site_key in HOSTS:
                if site_key not in record["sites"]:
                    continue
                soup = BeautifulSoup(
                    self.client.get(f"/articles/{slug}", headers={"Host": host}).get_data(as_text=True),
                    "html.parser",
                )
                hrefs = {a["href"] for a in soup.find_all("a", href=True)}
                self.assertIn(expected_contact(site_key), hrefs, (slug, host))
                for href in hrefs:
                    if href.startswith("http") and "motorinn" in href:
                        self.assertTrue(href.startswith("https://www."), (slug, href))

    def test_discovery_outputs_list_allowed_and_exclude_disallowed(self) -> None:
        for record in server.article_catalog():
            slug = record["slug"]
            for host, site_key in HOSTS:
                allowed = site_key in record["sites"]
                url = f"https://{host}/articles/{slug}"
                path = f"/articles/{slug}"
                outputs = {
                    "sitemap.xml": self.client.get("/sitemap.xml", headers={"Host": host}).get_data(as_text=True),
                    "sitemap.html": self.client.get("/sitemap.html", headers={"Host": host}).get_data(as_text=True),
                    "llms.txt": self.client.get("/llms.txt", headers={"Host": host}).get_data(as_text=True),
                    "llms-full.txt": self.client.get("/llms-full.txt", headers={"Host": host}).get_data(as_text=True),
                    "ai.txt": self.client.get("/ai.txt", headers={"Host": host}).get_data(as_text=True),
                    "feed.json": self.client.get("/feed.json", headers={"Host": host}).get_data(as_text=True),
                }
                for name, body in outputs.items():
                    if allowed:
                        self.assertIn(path if name == "sitemap.html" else url, body, (slug, host, name))
                    else:
                        self.assertNotIn(url, body, (slug, host, name))
                links_slug = {
                    "motorinnautogroup": "motorinnautogroup",
                    "motorinntoyota": "motorinntoyotaofcarroll",
                    "motorinnchevy": "motorinnofcarroll",
                }[site_key]
                links_page = self.client.get(f"/links/{links_slug}.html", headers={"Host": host}).get_data(as_text=True)
                if allowed:
                    self.assertIn(url, links_page, (slug, host))
                else:
                    self.assertNotIn(url, links_page, (slug, host))

    def test_hub_footer_links_use_filtered_catalog(self) -> None:
        for host, site_key in HOSTS:
            site = server.SITES[site_key]
            links_page = self.client.get("/links/discovery-probe", headers={"Host": host})  # any 404 is fine
            hub_source = server.add_hub_footer_links("<html><body><main>x</main></body></html>", site)
            soup = BeautifulSoup(hub_source, "html.parser")
            hrefs = {a["href"] for a in soup.find_all("a")}
            for record in server.article_catalog():
                url = server.article_href(site, record["slug"])
                if site_key in record["sites"]:
                    self.assertIn(url, hrefs, (site_key, record["slug"]))
                else:
                    self.assertNotIn(url, hrefs, (site_key, record["slug"]))
            self.assertTrue(hrefs)

    def test_feed_json_has_one_entry_per_article_no_duplicates(self) -> None:
        import json as jsonlib

        for host, site_key in HOSTS:
            payload = jsonlib.loads(self.client.get("/feed.json", headers={"Host": host}).get_data(as_text=True))
            items = payload if isinstance(payload, list) else payload.get("items", payload)
            urls = [item["url"] for item in items]
            self.assertEqual(len(urls), len(set(urls)), site_key)
            for record in server.article_catalog():
                present = server.article_href(server.SITES[site_key], record["slug"]) in urls
                self.assertEqual(present, site_key in record["sites"], (site_key, record["slug"]))

    def test_query_search_indexes_articles_with_article_source(self) -> None:
        for host, site_key in HOSTS:
            site = server.SITES[site_key]
            docs = server.build_article_query_documents(site)
            by_slug = {doc.id.rsplit(":", 1)[1]: doc for doc in docs}
            for record in server.article_catalog():
                if site_key not in record["sites"]:
                    self.assertNotIn(record["slug"], by_slug, (site_key, record["slug"]))
                    continue
                doc = by_slug[record["slug"]]
                self.assertEqual(doc.source_url, server.article_href(site, record["slug"]))
                self.assertEqual(doc.canonical_url, doc.source_url)
                self.assertEqual(doc.source_type, "article")
                self.assertTrue(doc.body.strip())
                self.assertNotIn("<", doc.body[:200])

    def test_query_endpoint_returns_article_result(self) -> None:
        for record in server.article_catalog():
            slug = record["slug"]
            host, site_key = next((h, k) for h, k in HOSTS if k in record["sites"])
            site = server.SITES[site_key]
            docs = server.build_article_query_documents(site)
            token = QUERY_TOKENS[slug].strip()
            with patch.object(server, "build_query_documents", return_value=docs):
                response = self.client.get(
                    f"/llms/json?query={token}&limit=5", headers={"Host": host}
                )
            self.assertEqual(response.status_code, 200, slug)
            import json as jsonlib

            payload = jsonlib.loads(response.get_data(as_text=True))
            ids = {result["id"] for result in payload["results"]}
            self.assertIn(f"{site_key}:article:{slug}", ids, (slug, ids))


class ExistingArticleRegressionTests(unittest.TestCase):
    """The original per-site rewrite behaviour on the pre-existing article."""

    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_used_trucks_route_serves_host_canonical_and_links(self) -> None:
        slug = "used-trucks-towing-iowa"
        for host, site_key in HOSTS:
            response = self.client.get(f"/articles/{slug}", headers={"Host": host})
            self.assertEqual(response.status_code, 200, host)
            self.assertEqual(response.headers.get("X-Robots-Tag"), "index, follow", host)
            soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
            self.assertEqual(soup.find("link", rel="canonical")["href"], f"https://{host}/articles/{slug}", host)
            hrefs = {a["href"] for a in soup.find_all("a")}
            links_site = server.SITES[server.HOST_TO_SITE[host]]
            self.assertIn(f"/links/{links_site.key}.html", hrefs, hrefs)
            self.assertIn("/used-inventory.md", hrefs)
            self.assertIn(expected_contact(site_key), hrefs)
            self.assertIn("https://www.chevrolet.com/trucks/silverado/1500", hrefs)


if __name__ == "__main__":
    unittest.main()
