from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

import server


def _site():
    return server.SITES["motorinnautogroup"]


class SeoLadderTests(unittest.TestCase):
    def test_heading_ladder_completes_h5_h6(self) -> None:
        html = "<html><body><h1>Used Trucks</h1><h2>Shop</h2></body></html>"
        out = server.complete_heading_ladder(html, _site())
        soup = BeautifulSoup(out, "html.parser")
        self.assertIsNotNone(soup.find("h5"))
        self.assertIsNotNone(soup.find("h6"))
        again = BeautifulSoup(server.complete_heading_ladder(out, _site()), "html.parser")
        self.assertEqual(len(again.find_all("h5")), 1)

    def test_heading_ladder_full_ladder_untouched(self) -> None:
        html = "<html><body>" + "".join(f"<h{i}>x</h{i}>" for i in range(1, 7)) + "</body></html>"
        out = server.complete_heading_ladder(html, _site())
        self.assertIsNone(BeautifulSoup(out, "html.parser").find(id="heading-ladder"))

    def test_entity_schema_on_subpages(self) -> None:
        html = "<html><head></head><body><p>inventory</p></body></html>"
        out = server.add_entity_schema_to_pages(html, _site(), "/used-inventory")
        soup = BeautifulSoup(out, "html.parser")
        script = soup.find("script", id="motorinn-entity")
        self.assertIsNotNone(script)
        self.assertIn("AutoDealer", script.string)
        again = BeautifulSoup(server.add_entity_schema_to_pages(out, _site(), "/used-inventory"), "html.parser")
        self.assertEqual(len(again.find_all("script", id="motorinn-entity")), 1)

    def test_hub_footer_links_added_once(self) -> None:
        html = "<html><body><h1>Service</h1></body></html>"
        out = server.add_hub_footer_links(html, _site())
        self.assertIsNotNone(BeautifulSoup(out, "html.parser").find(id="motorinn-hub-nav"))
        again = server.add_hub_footer_links(out, _site())
        self.assertEqual(len(BeautifulSoup(again, "html.parser").find_all(id="motorinn-hub-nav")), 1)

    def test_inject_related_links_applies_seo_layers(self) -> None:
        page = server.inject_related_links(
            "<html><body><main>Root page</main></body></html>", _site(), "/"
        )
        soup = BeautifulSoup(page, "html.parser")
        self.assertIsNotNone(soup.find("script", id="motorinn-entity"))
        self.assertIsNotNone(soup.find(id="motorinn-hub-nav"))


if __name__ == "__main__":
    unittest.main()
