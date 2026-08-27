from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "dealeron-discovery-handoff"
SITES = {
    "motorinnautogroup.com": "ai.motorinnautogroup.com",
    "motorinntoyotaofcarroll.com": "ai.motorinntoyotaofcarroll.com",
    "motorinnofcarroll.com": "ai.motorinnofcarroll.com",
}


class DealerOnDiscoveryHandoffTests(unittest.TestCase):
    def test_each_site_has_discovery_files_for_only_its_matching_host(self) -> None:
        all_hosts = set(SITES.values())
        for site, host in SITES.items():
            directory = HANDOFF / site
            for filename in ("llms.txt", "llms-full.txt", "robots-additions.txt"):
                self.assertTrue((directory / filename).is_file(), f"missing {site}/{filename}")
            discovery = "\n".join(
                (directory / filename).read_text(encoding="utf-8")
                for filename in ("llms.txt", "llms-full.txt")
            )
            self.assertIn(f"https://{host}/llms.txt", discovery)
            for other_host in all_hosts - {host}:
                self.assertNotIn(other_host, discovery)

    def test_crawler_policy_allows_search_and_blocks_training(self) -> None:
        for site in SITES:
            policy = (HANDOFF / site / "robots-additions.txt").read_text(encoding="utf-8")
            self.assertIn("User-agent: OAI-SearchBot\nAllow: /", policy)
            self.assertIn("User-agent: Claude-SearchBot\nAllow: /", policy)
            self.assertIn("User-agent: GPTBot\nDisallow: /", policy)
            self.assertIn("User-agent: ClaudeBot\nDisallow: /", policy)

    def test_handoff_covers_inventory_service_and_parts_for_agents(self) -> None:
        request = (HANDOFF / "DEALERON_REQUEST.md").read_text(encoding="utf-8")
        page_requirements = (HANDOFF / "SITE_PAGE_REQUIREMENTS.md").read_text(
            encoding="utf-8"
        )
        acceptance = (HANDOFF / "ACCEPTANCE_CHECKLIST.md").read_text(
            encoding="utf-8"
        )

        for capability in ("vehicle", "service", "parts"):
            self.assertIn(capability, request.casefold())
            self.assertIn(capability, page_requirements.casefold())
            self.assertIn(capability, acceptance.casefold())
        self.assertIn("one physical service location", page_requirements.casefold())
        self.assertIn("1526 Le Clark Road", page_requirements)
        self.assertIn("do not create three Xtime locations", page_requirements)

    def test_discovery_files_link_the_public_agent_contracts(self) -> None:
        for site, host in SITES.items():
            discovery = (HANDOFF / site / "llms.txt").read_text(encoding="utf-8")
            for path in (
                "/openapi.json",
                "/mcp",
                "/api/v1/vehicles",
                "/api/v1/service-information",
                "/api/v1/parts-information",
                "/service-scheduler",
            ):
                self.assertIn(f"https://{host}{path}", discovery)


if __name__ == "__main__":
    unittest.main()
